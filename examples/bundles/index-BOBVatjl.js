function portSpeedCurrent(){return L.read("/admin/network?form=port_speed_current",{preventError:true})}
function setPortSpeedCurrent(e){return L.write("/admin/network?form=port_speed_current",e,{preventSuccess:true})}
function portSpeedSupported(){return L.read("/admin/network?form=port_speed_supported",{preventError:true})}
function wanFlow(){return L.read("/admin/network?form=wan_fc",{preventError:true})}
function setWanFlow(e){return L.write("/admin/network?form=wan_fc",e,{preventSuccess:true})}
