'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ThemeProvider, useTheme } from 'next-themes';
import { Moon, Sun, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
function Header(){
 const {resolvedTheme,setTheme}=useTheme();const path=usePathname();
 return <header className="topbar"><Link className="brand" href="/"><ShieldCheck size={20} aria-hidden="true"/><span>Dispute-Safe Collections</span><span className="demo-label">Demo</span></Link><nav aria-label="Main navigation"><span className="header-mode">Text first / Voice opt-in</span><Link href="/evals" aria-current={path==='/evals'?'page':undefined}>Evaluations</Link><Button variant="ghost" size="icon" aria-label="Toggle light or dark theme" onClick={()=>setTheme(resolvedTheme==='dark'?'light':'dark')}><Sun className="dark:hidden" size={16}/><Moon className="hidden dark:block" size={16}/></Button></nav></header>;
}
export function AppChrome({children}:{children:React.ReactNode}){return <ThemeProvider attribute="class" defaultTheme="system" enableSystem><a className="skip-link" href="#main-content">Skip to main content</a><Header/><div id="main-content">{children}</div></ThemeProvider>;}
