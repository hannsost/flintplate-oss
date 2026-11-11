"use client";
import { cloneElement, isValidElement, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ArrowUpRight, Download, LoaderCircle, LogOut, Sparkles, WifiOff, X } from "lucide-react";
import { auth } from "@/lib/auth";

export function Mark({compact=false}:{compact?:boolean}) { return <span className="fp-brand"><svg width="39" height="39" viewBox="0 0 48 48" fill="none" aria-hidden="true"><circle cx="20.5" cy="30" r="11.5" stroke="currentColor" strokeWidth="2.4"/><path d="M29.8 23.5 40.8 17" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"/><path d="m8.5 11.5 1.25 3.5 3.5 1.25-3.5 1.25-1.25 3.5-1.25-3.5L3.75 16.25l3.5-1.25Z" fill="currentColor"/><path d="m18 6 1.5 4.15 4.15 1.5-4.15 1.5L18 17.3l-1.5-4.15-4.15-1.5 4.15-1.5Z" fill="currentColor"/><path d="m28 10.5 1 2.75 2.75 1-2.75 1-1 2.75-1-2.75-2.75-1 2.75-1Z" fill="currentColor"/></svg>{!compact&&<span>flintplate<span className="fp-by">by neurofunken</span></span>}</span>; }
export function Tag({children,tone="neutral"}:{children:ReactNode;tone?:string}) {return <span className={`fp-tag ${tone}`}>{children}</span>;}
export function Empty({title,children}:{title:string;children?:ReactNode}) {return <div className="fp-empty"><Sparkles size={24}/><h3>{title}</h3><p>{children}</p></div>;}
export function Loading(){return <div className="fp-loading" role="status"><LoaderCircle className="fp-spin" size={24}/> FlintPlate wird geladen …</div>;}
export function Modal({title,onClose,children,closeDisabled=false}:{title:string;onClose:()=>void;children:ReactNode;closeDisabled?:boolean}) {
 const panel=useRef<HTMLElement>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;const root=panel.current;const selector='button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]';root?.querySelector<HTMLElement>(selector)?.focus();const trap=(e:KeyboardEvent)=>{if(e.key!=="Tab"||!root)return;const targets=Array.from(root.querySelectorAll<HTMLElement>(selector)).filter(el=>el.getClientRects().length>0);const first=targets[0],last=targets.at(-1);if(!first){e.preventDefault();root.focus();}else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}};root?.addEventListener("keydown",trap);const oldOverflow=document.body.style.overflow;document.body.style.overflow="hidden";return()=>{root?.removeEventListener("keydown",trap);document.body.style.overflow=oldOverflow;previous?.focus();};},[]);
 useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==="Escape"&&!closeDisabled)onClose();};document.addEventListener("keydown",handler);return()=>document.removeEventListener("keydown",handler);},[onClose,closeDisabled]);
 return <div className="fp-backdrop"><section ref={panel} tabIndex={-1} className="fp-modal" role="dialog" aria-modal="true" aria-label={title}><div className="fp-section-head"><h2>{title}</h2><button className="fp-icon" aria-label="Dialog schließen" disabled={closeDisabled} onClick={onClose}><X size={22}/></button></div>{children}</section></div>;
}
export function Field({label,children}:{label:string;children:ReactNode}) {const generated=useId();const child=isValidElement<{id?:string}>(children)?children:null;const id=child?.props.id??generated;return <div className="fp-field"><label htmlFor={id}>{label}</label>{child?cloneElement(child,{id}):children}</div>;}
export function Logout(){return <button className="fp-icon" aria-label="Abmelden" onClick={()=>{auth.clear();window.location.assign("/anmelden");}}><LogOut size={19}/></button>;}
export function LinkCard({href,title,children}:{href:string;title:string;children:ReactNode}){return <a className="fp-link-card" href={href}><div><h3>{title}</h3><p>{children}</p></div><ArrowUpRight size={21}/></a>;}
interface InstallEvent extends Event { prompt:()=>Promise<void>; userChoice:Promise<{outcome:string}> }
export function MobileRuntime({manifest}:{manifest:string}) {
 const [offline,setOffline]=useState(false);const [install,setInstall]=useState<InstallEvent|null>(null);const [help,setHelp]=useState(false);
 useEffect(()=>{const online=()=>setOffline(!navigator.onLine);online();window.addEventListener("online",online);window.addEventListener("offline",online);
 const handler=(e:Event)=>{e.preventDefault();setInstall(e as InstallEvent);};window.addEventListener("beforeinstallprompt",handler);
 const link=document.createElement("link");link.rel="manifest";link.href=manifest;document.head.appendChild(link);
 if("serviceWorker" in navigator)navigator.serviceWorker.register("/flintplate-sw.js").catch(()=>{});
 return()=>{window.removeEventListener("online",online);window.removeEventListener("offline",online);window.removeEventListener("beforeinstallprompt",handler);link.remove();};},[manifest]);
 return <>{offline&&<div className="fp-notice error" role="alert"><WifiOff size={18}/> Keine Verbindung. Aktionen erst nach Wiederverbindung senden; offene Eingaben bleiben hier erhalten.</div>}<button className="fp-install" onClick={async()=>{if(install){await install.prompt();await install.userChoice;setInstall(null);}else setHelp(!help);}}><Download size={16}/> App installieren</button>{help&&<p className="fp-install-help">iPhone: In Safari „Teilen“ → „Zum Home-Bildschirm“. Android: Browsermenü → „App installieren“. Die Installation benötigt HTTPS oder localhost.</p>}</>;
}

/** Keeps a view current while it is on screen. A failed background poll stays
 *  silent; the next tick tries again and any explicit action still reports. */
export function useLive(load:()=>Promise<unknown>,ms=15000){
 const latest=useRef(load);
 useEffect(()=>{latest.current=load;},[load]);
 useEffect(()=>{
  const tick=()=>{if(document.visibilityState==="visible")void latest.current().catch(()=>undefined);};
  const timer=setInterval(tick,ms);
  document.addEventListener("visibilitychange",tick);
  return()=>{clearInterval(timer);document.removeEventListener("visibilitychange",tick);};
 },[ms]);
}

/** A clock that moves on its own, so elapsed times stay honest without a request. */
export function useNow(ms=30000){
 const [now,setNow]=useState(()=>Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),ms);return()=>clearInterval(timer);},[ms]);
 return now;
}

export function minutesSince(iso:string,now:number){
 return Math.max(0,Math.floor((now-new Date(iso).getTime())/60000));
}

export function since(iso:string,now:number){
 const minutes=minutesSince(iso,now);
 if(minutes<1)return "gerade eben";
 if(minutes<60)return `seit ${minutes} Min.`;
 const hours=Math.floor(minutes/60);
 return `seit ${hours} Std. ${minutes%60} Min.`;
}
