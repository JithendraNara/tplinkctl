const routes=[
  {name:"internetBasic",path:"internetBasic",component:()=>o(()=>import("./index-C7vSxU-K.js"))},
  {name:"internetAdv",path:"internetAdv",component:()=>o(()=>import("./index-BOBVatjl.js"))}
];
function statusIpv4(){return v.read("/admin/network?form=status_ipv4",{preventError:true})}
function wanIpv4Status(){return v.read("/admin/network?form=wan_ipv4_status",{preventError:true})}
function wanIpv4Protos(){return v.request("/admin/network?form=wan_ipv4_protos",{operation:"read"})}
