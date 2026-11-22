'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useDataChannel, type UseSessionReturn } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';
import { EvidenceEvent, eventSchema } from '@/lib/events';

export function useEvidence(session:UseSessionReturn,agentIdentity:string|undefined,sessionId:string){
 const [events,setEvents]=useState<EvidenceEvent[]>([]);
 const [syncError,setSyncError]=useState('');
 const journal=useRef(new Map<number,EvidenceEvent>());
 const sequence=useRef(0);
 const syncing=useRef(false);
 const sync=useCallback(async()=>{
  if(!agentIdentity||!session.isConnected||syncing.current)return;
  syncing.current=true;
  try{await session.room.localParticipant.performRpc({destinationIdentity:agentIdentity,method:'collections.sync',payload:JSON.stringify({after:sequence.current})});setSyncError('');}
  catch{setSyncError('Evidence sync failed. Reconnect to request replay; no tool results are assumed.');}
  finally{syncing.current=false;}
 },[agentIdentity,session.isConnected,session.room]);
 useDataChannel('collections.events',message=>{
  if(!agentIdentity||message.from?.identity!==agentIdentity||message.payload.byteLength>=8192)return;
  try{
   const parsed=eventSchema.safeParse(JSON.parse(new TextDecoder().decode(message.payload)));
   if(!parsed.success||parsed.data.session_id!==sessionId)return;
   const event=parsed.data;
   if(journal.current.has(event.seq))return;
   journal.current.set(event.seq,event);
   while(journal.current.has(sequence.current+1))sequence.current++;
   setEvents([...journal.current.values()].filter(e=>e.seq<=sequence.current).sort((a,b)=>a.seq-b.seq));
   if(event.seq>sequence.current+1)void sync();
  }catch{/* Reject malformed or untrusted packets, never render HTML. */}
 });
 useEffect(()=>{
  void sync();
  session.room.on(RoomEvent.Reconnected,sync);
  return ()=>{session.room.off(RoomEvent.Reconnected,sync);};
 },[session.room,sync]);
 return {events,syncError,retrySync:sync};
}
