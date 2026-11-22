import { z } from 'zod';
const source=z.object({tool_call_id:z.string(),json_pointer:z.string()});
export const factSchema=z.object({fact_id:z.string(),text:z.string(),sources:z.array(source),collection:z.boolean().optional()});
const result=z.object({ok:z.boolean(),code:z.string(),data:z.record(z.string(),z.unknown()),facts:z.array(factSchema)});
const payloads=z.discriminatedUnion('type',[
 z.object({type:z.literal('tool_call'),payload:z.object({call_id:z.string(),name:z.string(),inputs:z.record(z.string(),z.unknown()),actor:z.enum(['model','policy'])})}),
 z.object({type:z.literal('tool_result'),payload:z.object({call_id:z.string(),result})}),
 z.object({type:z.literal('reply_sources'),payload:z.object({message_id:z.string(),text:z.string(),facts:z.array(factSchema),non_factual:z.object({acknowledgement:z.string(),question:z.string()})})}),
 z.object({type:z.literal('case_state'),payload:z.object({case_id:z.string().nullable(),collection_hold:z.boolean(),contact_suppressed:z.boolean(),simulated:z.literal(true)})}),
 z.object({type:z.literal('voice_state'),payload:z.object({enabled:z.boolean(),available:z.boolean().optional(),lease_id:z.string().nullable().optional(),message:z.string().optional()})}),
 z.object({type:z.literal('limit'),payload:z.object({message:z.string()})}),
 z.object({type:z.literal('error'),payload:z.object({code:z.string(),message:z.string()})}),
 z.object({type:z.literal('latency'),payload:z.object({message_id:z.string(),unit:z.literal('seconds'),metrics:z.record(z.string(),z.unknown())})}),
]);
export const eventSchema=z.intersection(z.object({v:z.literal(1),seq:z.number().int().positive().max(500),session_id:z.string(),turn_id:z.string()}),payloads);
export type EvidenceEvent=z.infer<typeof eventSchema>;
export type Fact=z.infer<typeof factSchema>;

export function pointerValue(value:unknown,pointer:string):unknown{
 return pointer.split('/').slice(1).reduce<unknown>((current,key)=>{
  const decoded=key.replace(/~1/g,'/').replace(/~0/g,'~');
  if(current===null||typeof current!=='object') return undefined;
  return (current as Record<string,unknown>)[decoded];
 },value);
}
