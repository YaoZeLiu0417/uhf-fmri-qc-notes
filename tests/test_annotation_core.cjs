const assert=require('node:assert/strict');
require('../web/ppg_annotation_core.js');
const C=globalThis.PPGAnnotationCore;
const d={fingerprint:'f'.repeat(64),selection_condition:'synthetic test',cases:[
  {case_id:'C01',duration_s:3,sampling_frequency:10,first_sample_time_s:.02,samples:Array(30).fill(2048)},
  {case_id:'C02',duration_s:3,sampling_frequency:10,first_sample_time_s:.02,samples:Array(30).fill(2048)}]};
const m={reviewer:'test',review_date:'2026-10-25',fiducial:'ppg_peak',definition:'one defined peak per waveform',prior_exposure:'no'};
let s=C.emptySession(d),r=s.cases[0],c=d.cases[0];
assert.equal(C.snapIndex(c,.167),1);
assert.ok(Math.abs(C.timeAt(c,1)-.12)<1e-12);
assert.equal(C.toExport(s,d).cases[0].pulse_times_seconds_from_window_onset,null);
assert.throws(()=>C.canComplete(r,c));
r.metadata=m;r.status='in_progress';r.sample_indices=[1,12];
assert.equal(C.canComplete(r,c),true);
r.uncertain_intervals_s=[[.1,.4]];assert.throws(()=>C.canComplete(r,c),/冲突/);
r.uncertain_intervals_s=[[2,3]];r.status='completed';
const exported=C.toExport(s,d),restored=C.fromImport(exported,d);
assert.deepEqual(restored.cases,s.cases);
assert.equal(exported.cases[1].pulse_times_seconds_from_window_onset,null);
assert.throws(()=>C.fromImport({...exported,dataset_fingerprint:'x'},d),/指纹/);
let bad=C.clone(exported);bad.cases[0].sample_indices=[2,2];assert.throws(()=>C.fromImport(bad,d),/重复/);
bad=C.clone(exported);bad.cases[0].pulse_times_seconds_from_window_onset[0]=1.4;assert.throws(()=>C.fromImport(bad,d),/不一致/);
bad=C.clone(exported);bad.cases[0].uncertain_intervals_s=[[0,3.5]];assert.throws(()=>C.fromImport(bad,d),/超出/);
bad=C.clone(exported);bad.cases[0].metadata.review_date='2026-02-30';assert.throws(()=>C.fromImport(bad,d),/日期/);
assert.deepEqual(C.mergeRanges([[2,3],[1,2.5],[0,.4]]),[[0,.4],[1,3]]);
r.sample_indices=[];r.uncertain_intervals_s=[[1,3]];assert.throws(()=>C.canComplete(r,c),/整窗/);
r.uncertain_intervals_s=[[0,3]];assert.equal(C.canComplete(r,c),true);
console.log('PASS: sample snapping, unknown-versus-zero, completion guards, uncertainty, import/export and invalid-input checks');
