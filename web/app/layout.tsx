import './globals.css';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import { AppChrome } from '@/components/app-chrome';
export const metadata={title:'Dispute-Safe Collections — fake-data demo',description:'A tool-grounded invoice demo with inspectable evidence. No real payments, emails or human handoff.'};
export default function Layout({children}:{children:React.ReactNode}){
 return <html lang="en" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}><body><AppChrome>{children}</AppChrome></body></html>;
}
