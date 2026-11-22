import 'server-only';
import { Redis } from '@upstash/redis';
import { SignJWT, jwtVerify } from 'jose';
import { createHmac, randomUUID } from 'node:crypto';
import { cookies } from 'next/headers';

const enc = new TextEncoder();
export const WORKER = 'dispute-safe-collections';
export type Binding = {session_id:string; visitor_id:string; ip_hash:string; participant_identity:string; room:string; customer_id:'CUST-1001'; invoice_id:'INV-2026-1042'; prompt_version:'v1'|'v2'; deadline:number};
export class AdmissionError extends Error { constructor(message:string, public status=503){ super(message); } }
export function env(name:string){ const value=process.env[name]; if(!value) throw new AdmissionError('Service unavailable: required server configuration is missing.'); return value; }
export function store(){ return new Redis({url:env('UPSTASH_REDIS_REST_URL'),token:env('UPSTASH_REDIS_REST_TOKEN'),retry:false}); }
export function originCheck(request:Request){ if(request.headers.get('origin') !== new URL(env('PUBLIC_APP_URL')).origin) throw new AdmissionError('Origin not allowed.',403); }
export async function visitor(create=false){
 const jar=await cookies(); const secret=env('VISITOR_COOKIE_SECRET');
 if(secret.length<32) throw new AdmissionError('Service unavailable: cookie signing secret is too short.');
 const token=jar.get('collections_visitor')?.value;
 if(token){ try { const {payload}=await jwtVerify(token,enc.encode(secret),{algorithms:['HS256'],issuer:WORKER,audience:'visitor'}); if(typeof payload.sub==='string') return payload.sub; } catch { /* Invalid cookie has no ownership. */ } }
 if(!create) throw new AdmissionError('Session ownership could not be verified.',403);
 const id=randomUUID();
 const signed=await new SignJWT({}).setProtectedHeader({alg:'HS256'}).setSubject(id).setIssuer(WORKER).setAudience('visitor').setIssuedAt().setExpirationTime('30d').sign(enc.encode(secret));
 jar.set('collections_visitor',signed,{httpOnly:true,secure:true,sameSite:'lax',path:'/',maxAge:2592000});
 return id;
}
export function ipHash(request:Request){
 const ip=request.headers.get('x-vercel-forwarded-for')?.split(',')[0]?.trim();
 if(!ip && process.env.NODE_ENV==='production') throw new AdmissionError('Trusted deployment IP unavailable.');
 return createHmac('sha256',env('IP_HASH_SECRET')).update(ip || 'local-development').digest('hex');
}
export async function budgetAvailable(redis:Redis, scope:'public-text'|'public-voice'){
 const amount=Number(process.env[scope==='public-text'?'PUBLIC_TEXT_BUDGET_USD':'PUBLIC_VOICE_BUDGET_USD']||0);
 const total=Number(process.env.TOTAL_PROVIDER_BUDGET_USD||0);
 if(!Number.isFinite(amount)||!Number.isFinite(total)||amount<=0||total<=0) throw new AdmissionError('Provider calls disabled: approved budget is zero.');
 for(const [name,ceiling] of [[scope,amount],['total',total]] as const){
  const used=Number(await redis.get(`collections:budget:${env('BUDGET_CAMPAIGN_ID')}:${name}`)||0);
  if(!Number.isFinite(used)||used>=Math.floor(ceiling*1e6)) throw new AdmissionError('Provider budget exhausted.',429);
 }
}
export async function bindingToken(binding:Binding){
 return new SignJWT(binding).setProtectedHeader({alg:'HS256'}).setIssuer(WORKER).setAudience('worker').setIssuedAt().setExpirationTime(binding.deadline).sign(enc.encode(env('LIVEKIT_API_SECRET')));
}
export async function owned(redis:Redis, visitorId:string, sessionId:string){
 const binding=await redis.get<Binding>(`collections:session:${sessionId}`);
 if(!binding||binding.visitor_id!==visitorId||binding.deadline<=Date.now()/1000) throw new AdmissionError('This demo session has ended. Start a new demo.',403);
 return binding;
}
export async function release(redis:Redis,binding:Binding){
 await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",[`collections:occupancy:${binding.visitor_id}`],[binding.session_id]);
}
