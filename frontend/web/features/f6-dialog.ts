import type { KeyboardEvent } from "react";
// Keep keyboard focus inside F6 confirmations, including the browser-chrome Tab boundary.
export function trapConfirmationFocus(event:KeyboardEvent<HTMLDialogElement>){
 if(event.key!=="Tab")return;
 const nodes=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href]'));
 if(!nodes.length){event.preventDefault();event.currentTarget.focus();return;}
 const first=nodes[0],last=nodes[nodes.length-1],focused=event.currentTarget.ownerDocument.activeElement;
 if(event.shiftKey&&focused===first){event.preventDefault();last.focus();}
 else if(!event.shiftKey&&focused===last){event.preventDefault();first.focus();}
}
