import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./flintplate.css";
const manrope=localFont({src:"./fonts/manrope.woff2",variable:"--font-inter",display:"swap"});
export const metadata:Metadata={title:"FlintPlate · Gastronomie & Erlebnisse",description:"Betrieb, Gäste und Team. Eine Plattform von neurofunken auf Palmscout-Personalbasis.",applicationName:"FlintPlate",icons:{icon:"/flintplate/icon.svg",apple:"/flintplate/apple-touch-icon.png"},appleWebApp:{capable:true,statusBarStyle:"default",title:"FlintPlate"}};
export const viewport:Viewport={width:"device-width",initialScale:1,viewportFit:"cover",themeColor:"#173f31"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="de" className={manrope.variable}><body>{children}</body></html>;}
