import type { NextConfig } from "next";
const nextConfig:NextConfig={output:"standalone",experimental:{useTypeScriptCli:false,cpus:2},async rewrites(){return [{source:"/api/:path*",destination:`${process.env.FLINTPLATE_API_URL??"http://127.0.0.1:8012"}/:path*`}];},async headers(){return [{source:"/flintplate-sw.js",headers:[{key:"Cache-Control",value:"no-cache"},{key:"Service-Worker-Allowed",value:"/"}]}];}};
export default nextConfig;
