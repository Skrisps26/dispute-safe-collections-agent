import { Workspace } from '@/components/workspace';
export const dynamic='force-dynamic';
export default function Page(){
 return <Workspace textAvailable={process.env.TEXT_ENABLED==='true'} voiceAvailable={process.env.VOICE_ENABLED==='true'} promptVersion={process.env.PROMPT_VERSION||'v2'}/>;
}
