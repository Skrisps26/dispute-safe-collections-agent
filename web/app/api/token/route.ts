import { NextResponse } from 'next/server';
import { AccessToken, type VideoGrant } from 'livekit-server-sdk';
import { RoomConfiguration, RoomAgentDispatch, TrackSource } from '@livekit/protocol';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { AdmissionError, WORKER, env, store, originCheck, visitor, ipHash, budgetAvailable, bindingToken, owned, release, type Binding } from '@/lib/access';

export const revalidate=0;
export const runtime='nodejs';
const bodySchema=z.discriminatedUnion('action',[
 z.object({action:z.literal('connect')}).strict(),
 z.object({action:z.literal('voice'),session_id:z.string().uuid(),enabled:z.boolean()}).strict(),
]);
const headers={'Cache-Control':'no-store'};

export async function POST(request:Request){
 try{
  // Disabled service never accesses Redis, mints a token or dispatches a worker.
  if(process.env.TEXT_ENABLED!=='true')throw new AdmissionError('Provider calls disabled / credentials unavailable. No live agent is running.');
  originCheck(request);
  if(Number(request.headers.get('content-length')||0)>1024)throw new AdmissionError('Request too large.',413);
  const raw=await request.text();
  if(new TextEncoder().encode(raw).length>1024)throw new AdmissionError('Request too large.',413);
  const parsed=bodySchema.safeParse(JSON.parse(raw));
  if(!parsed.success)throw new AdmissionError('Invalid request. Room and account identifiers are server-bound.',400);
  const body=parsed.data;
  env('LIVEKIT_URL');env('LIVEKIT_API_KEY');env('LIVEKIT_API_SECRET');
  const redis=store();
  if(body.action==='voice'){
   const visitorId=await visitor();
   const binding=await owned(redis,visitorId,body.session_id);
   if(!body.enabled)return NextResponse.json({enabled:false},{headers});
   if(process.env.VOICE_ENABLED!=='true'||Number(process.env.GNANI_MAX_COST_PER_CALL_USD||0)<=0)throw new AdmissionError('Voice disabled: verified speech pricing and credit safeguards are required.');
   await budgetAvailable(redis,'public-voice');
   const leaseId=randomUUID();
   const admitted=await redis.set(`collections:voice-pending:${binding.session_id}`,leaseId,{nx:true,ex:30});
   if(!admitted)throw new AdmissionError('Voice activation already pending.',409);
   await redis.set(`collections:voice-lease:${leaseId}`,{session_id:binding.session_id,visitor_id:visitorId,participant_identity:binding.participant_identity,expires:Math.min(binding.deadline,Date.now()/1000+30)},{ex:30});
   return NextResponse.json({leaseId,enabled:false,status:'Awaiting worker authorization'},{headers});
  }
  await budgetAvailable(redis,'public-text');
  const visitorId=await visitor(true);
  const prompt=process.env.PROMPT_VERSION||'v2';
  if(prompt!=='v1'&&prompt!=='v2')throw new AdmissionError('Invalid prompt configuration.');
  const binding:Binding={session_id:randomUUID(),visitor_id:visitorId,ip_hash:ipHash(request),participant_identity:randomUUID(),room:randomUUID(),customer_id:'CUST-1001',invoice_id:'INV-2026-1042',prompt_version:prompt,deadline:Math.floor(Date.now()/1000)+600};
  const acquired=await redis.set(`collections:occupancy:${visitorId}`,binding.session_id,{nx:true,ex:600});
  if(!acquired)throw new AdmissionError('One demo session is already active. Close it or wait for its deadline.',409);
  try{
   await redis.set(`collections:session:${binding.session_id}`,binding,{ex:600});
   const signed=await bindingToken(binding);
   const roomConfig=new RoomConfiguration({agents:[new RoomAgentDispatch({agentName:WORKER,metadata:JSON.stringify({bindingJwt:signed})})]});
   const participantToken=await createParticipantToken(binding,roomConfig);
   return NextResponse.json({serverUrl:env('LIVEKIT_URL'),participantToken,sessionId:binding.session_id},{headers});
  }catch(error){await release(redis,binding);throw error;}
 }catch(error){
  const status=error instanceof AdmissionError?error.status:error instanceof SyntaxError?400:503;
  const message=error instanceof AdmissionError?error.message:status===400?'Invalid JSON request.':'Service unavailable: the shared quota store or configuration could not be verified.';
  return NextResponse.json({error:message},{status,headers});
 }
}

// Hardened version of the Agents UI registry helper: no client room config.
function createParticipantToken(binding:Binding,roomConfig:RoomConfiguration){
 const token=new AccessToken(env('LIVEKIT_API_KEY'),env('LIVEKIT_API_SECRET'),{identity:binding.participant_identity,ttl:'2m'});
 const grant:VideoGrant={room:binding.room,roomJoin:true,canSubscribe:true,canPublish:true,canPublishData:true,canPublishSources:[TrackSource.MICROPHONE],canUpdateOwnMetadata:false,roomCreate:false,roomList:false,roomAdmin:false,roomRecord:false,ingressAdmin:false};
 token.addGrant(grant);
 token.roomConfig=roomConfig;
 return token.toJwt();
}
