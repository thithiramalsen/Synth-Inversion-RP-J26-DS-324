"use strict";
let example;
function element(tag, text) { const node=document.createElement(tag); if(text!==undefined) node.textContent=text; return node; }
function render() {
  const show=document.getElementById('show-q').checked;
  document.getElementById('q-heading').hidden=!show;
  document.getElementById('meaning').hidden=!show;
  document.getElementById('comprehension').hidden=!show;
  const body=document.getElementById('controls'); body.replaceChildren();
  for(const p of example.parameters) {
    const row=element('tr'); row.append(element('td',p.label),element('td',(p.predicted_z*100).toFixed(1)));
    const probability=element('td',(p.q*100).toFixed(1)+'%'); probability.hidden=!show; row.append(probability);
    const answer=element('td'), select=element('select'); select.disabled=true; select.setAttribute('aria-label',p.label+' action example');
    for(const value of ['Choose an action','Retain','Check or adjust','Cannot judge']) select.append(element('option',value));
    answer.append(select); row.append(answer); body.append(row);
  }
}
for(const name of ['Usefulness for deciding what to check','Clarity','Decision confidence']) {
  const label=element('label',name+' '); const select=element('select'); select.disabled=true;
  for(const value of ['Choose a rating','1','2','3','4','5','Cannot judge']) select.append(element('option',value));
  label.append(select); document.getElementById('ratings').append(label,element('br'));
}
document.getElementById('show-q').addEventListener('change',()=>{if(example)render();});
document.querySelectorAll('audio').forEach(audio=>audio.addEventListener('play',()=>document.querySelectorAll('audio').forEach(other=>{if(other!==audio)other.pause();})));
fetch('/api/walkthrough').then(response=>{if(!response.ok)throw new Error('The preview could not be loaded.');return response.json();}).then(data=>{example=data;render();}).catch(error=>{document.getElementById('error').textContent=error.message;});
