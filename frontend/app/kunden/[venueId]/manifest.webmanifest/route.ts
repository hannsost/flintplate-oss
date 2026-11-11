export async function GET(_request:Request,{params}:{params:Promise<{venueId:string}>}) {
 const {venueId}=await params;if(!/^[0-9a-f-]{36}$/.test(venueId))return new Response("Not found",{status:404});
 return Response.json({id:`/kunden/${venueId}`,name:"FlintPlate Gäste",short_name:"FP Gäste",start_url:`/kunden/${venueId}`,scope:"/",display:"standalone",background_color:"#f7f7f0",theme_color:"#173f31",lang:"de",icons:[192,512].map(size=>({src:`/flintplate/icon-${size}.png`,sizes:`${size}x${size}`,type:"image/png",purpose:"any maskable"}))},{headers:{"Content-Type":"application/manifest+json","Cache-Control":"public, max-age=3600"}});
}
