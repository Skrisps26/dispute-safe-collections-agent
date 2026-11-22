'use client';
import { useState } from 'react';
import { FileSearch, ArrowUpRight } from 'lucide-react';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EvidenceEvent, pointerValue } from '@/lib/events';

export function EvidencePanel({events}:{events:EvidenceEvent[]}){
 const [open,setOpen]=useState<string[]>([]);
 const calls=events.filter(e=>e.type==='tool_call');
 const sources=events.filter(e=>e.type==='reply_sources');
 function focusCall(id:string){setOpen(v=>[...new Set([...v,id])]); requestAnimationFrame(()=>document.getElementById(`call-${id}`)?.focus());}
 return <section className="evidence-content" aria-label="Live evidence">
  <div className="panel-title"><h2>Live evidence</h2><Badge variant="outline">{calls.length} executions</Badge></div>
  <p className="secondary">Successful tool results are the only source of factual replies.</p>
  <ScrollArea className="evidence-scroll">
   {!calls.length ? <div className="empty-evidence"><FileSearch size={28} aria-hidden="true"/><h3>No tool activity yet</h3><p>Ask an invoice question to inspect tool inputs, results and the exact fields behind each fact.</p><p className="secondary">Nothing here is pre-filled or simulated as a live response.</p></div> : <>
    {sources.length>0 && <div className="source-list"><h3>Reply sources</h3>{sources.map(event=>event.type==='reply_sources'&&<div className="source-reply" key={event.seq}><p className="secondary">Message {event.payload.message_id}</p>{event.payload.facts.map(fact=><div className="source-fact" key={fact.fact_id}><p>{fact.text}</p>{fact.sources.map(source=>{
     const result=events.find(e=>e.type==='tool_result'&&e.payload.call_id===source.tool_call_id);
     const value=result?.type==='tool_result'?pointerValue(result.payload.result,source.json_pointer):undefined;
     return <div key={source.tool_call_id+source.json_pointer}><Button variant="link" onClick={()=>focusCall(source.tool_call_id)} className="source-link">{source.json_pointer}<ArrowUpRight size={12}/></Button><code className="cited-value">{JSON.stringify(value)??'Result not received yet'}</code></div>;
    })}</div>)}<p className="secondary">Courtesy and question: non-factual interface text.</p></div>)}</div>}
    <h3 className="section-label">Tool executions</h3><Accordion type="multiple" value={open} onValueChange={setOpen}>{calls.map(event=>{
     if(event.type!=='tool_call')return null;
     const call=event.payload;
     const output=events.find(e=>e.type==='tool_result'&&e.payload.call_id===call.call_id);
     const result=output?.type==='tool_result'?output.payload.result:null;
     return <AccordionItem key={call.call_id} value={call.call_id}><AccordionTrigger id={`call-${call.call_id}`}><span className="tool-name">{call.name}<span className="secondary">{call.actor==='policy'?'Policy execution':'Model tool call'}</span></span><Badge variant={result&&!result.ok?'destructive':'outline'}>{result?result.ok?'Success':result.code:'Running'}</Badge></AccordionTrigger><AccordionContent><p className="secondary mono">Call {call.call_id}</p><h4>Inputs</h4><pre>{JSON.stringify(call.inputs,null,2)}</pre><h4>Result</h4>{result?<><pre>{JSON.stringify(result.data,null,2)}</pre>{!result.ok&&<p role="status">{result.code}</p>}<Table><TableHeader><TableRow><TableHead>Fact</TableHead><TableHead>Source field</TableHead></TableRow></TableHeader><TableBody>{result.facts.map(f=><TableRow key={f.fact_id}><TableCell>{f.text}</TableCell><TableCell className="mono">{f.sources.map(s=>s.json_pointer).join(', ')}</TableCell></TableRow>)}</TableBody></Table></>:<p>Waiting for the actual result.</p>}</AccordionContent></AccordionItem>;
    })}</Accordion>
   </>}
   {events.filter(e=>e.type==='error'||e.type==='limit').map(e=><p className="event-error" role="status" key={e.seq}>{e.payload.message}</p>)}
  </ScrollArea>
 </section>;
}
