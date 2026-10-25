(function (root) {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const timeAt = (c, index) => c.first_sample_time_s + index / c.sampling_frequency;
  const snapIndex = (c, time) => Math.max(0, Math.min(c.samples.length - 1,
    Math.round((time - c.first_sample_time_s) * c.sampling_frequency)));
  const emptyCase = c => ({case_id:c.case_id, sample_indices:[], uncertain_intervals_s:[],
    note:'', metadata:null, status:'unreviewed'});
  const emptySession = d => ({schema_version:1, dataset_fingerprint:d.fingerprint,
    profile:{reviewer:'',review_date:'',fiducial:'',definition:'',prior_exposure:'unknown'},
    cases:d.cases.map(emptyCase)});

  function validateMetadata(m) {
    assert(m && typeof m.reviewer === 'string' && m.reviewer.trim(), '请填写复核者姓名或代号。');
    assert(/^\d{4}-\d{2}-\d{2}$/.test(m.review_date || ''), '请填写有效的复核日期。');
    const [y,month,day]=m.review_date.split('-').map(Number), date=new Date(Date.UTC(y,month-1,day));
    assert(date.getUTCFullYear()===y && date.getUTCMonth()===month-1 && date.getUTCDate()===day,
      '复核日期无效。');
    assert(['ppg_peak','max_upstroke','other'].includes(m.fiducial), '请先选择要标注的波形特征点。');
    assert(typeof m.definition === 'string' && m.definition.trim(), '请写下具体的事件定义。');
    assert(['no','yes','unknown'].includes(m.prior_exposure), '请记录是否看过算法结果。');
    return true;
  }

  function mergeRanges(ranges) {
    const sorted=ranges.map(x=>x.slice()).sort((a,b)=>a[0]-b[0]), merged=[];
    for (const [a,b] of sorted) {
      if (merged.length && a<=merged[merged.length-1][1]) merged[merged.length-1][1]=Math.max(b,merged[merged.length-1][1]);
      else merged.push([a,b]);
    }
    return merged;
  }

  function validateCase(record, c) {
    assert(record && record.case_id===c.case_id, '案例编码与数据不一致。');
    assert(['unreviewed','in_progress','completed'].includes(record.status), '标注状态无效。');
    assert(Array.isArray(record.sample_indices), '事件点格式无效。');
    assert(record.sample_indices.every((v,i,a)=>Number.isInteger(v) && v>=0 && v<c.samples.length && (!i || v>a[i-1])),
      '事件点必须是升序、无重复且在波形范围内的样本索引。');
    assert(Array.isArray(record.uncertain_intervals_s), '不确定区间格式无效。');
    assert(record.uncertain_intervals_s.every(x=>Array.isArray(x) && x.length===2 &&
      x.every(Number.isFinite) && 0<=x[0] && x[0]<x[1] && x[1]<=c.duration_s), '不确定区间超出窗口或顺序无效。');
    assert(typeof record.note==='string', '备注格式无效。');
    const touched=record.sample_indices.length || record.uncertain_intervals_s.length || record.status!=='unreviewed';
    if (touched) validateMetadata(record.metadata);
    else assert(record.metadata===null || typeof record.metadata==='object', '复核信息无效。');
    if (record.status==='unreviewed') assert(!record.sample_indices.length && !record.uncertain_intervals_s.length,
      '未标注状态不能包含事件点或区间。');
    return true;
  }

  function canComplete(record,c) {
    validateCase(record,c);
    validateMetadata(record.metadata);
    assert(record.sample_indices.length || record.uncertain_intervals_s.length, '请先标注事件或不确定区间。');
    const ranges=mergeRanges(record.uncertain_intervals_s);
    for (const index of record.sample_indices) {
      const t=timeAt(c,index);
      assert(!ranges.some(([a,b])=>a<=t && t<b), '事件点落在不确定区间内，请先缩小区间或移除冲突点。');
    }
    if (!record.sample_indices.length) assert(ranges.length===1 && ranges[0][0]===0 && ranges[0][1]===c.duration_s,
      '没有确定事件时，请将整窗列为不确定；空白不能解释为没有脉搏。');
    return true;
  }

  function toExport(session,d) {
    assert(session.dataset_fingerprint===d.fingerprint, '数据指纹不一致。');
    return {schema_version:1, dataset_fingerprint:d.fingerprint,
      annotation_scope:'Manual PPG waveform annotations, not independent ECG or hardware-timing validation.',
      selection_condition:d.selection_condition,
      exported_at:new Date().toISOString(), profile:clone(session.profile),
      cases:d.cases.map((c,i)=>{
        const r=session.cases[i];validateCase(r,c);
        if (r.status==='completed') canComplete(r,c);
        return {...clone(r),duration_s:c.duration_s,sampling_frequency:c.sampling_frequency,
          first_sample_time_s:c.first_sample_time_s,
          pulse_times_seconds_from_window_onset:r.status==='unreviewed'?null:r.sample_indices.map(x=>timeAt(c,x)),
          event_count_interpretation:r.uncertain_intervals_s.length?'Confident marked events only; uncertain intervals remain unlabelled.':'Marked candidates, not ECG-confirmed events.'};
      })};
  }

  function fromImport(value,d) {
    assert(value && value.schema_version===1 && value.dataset_fingerprint===d.fingerprint,
      '文件格式或数据指纹不匹配，未导入。');
    assert(Array.isArray(value.cases) && value.cases.length===d.cases.length, '案例数量不匹配。');
    const map=new Map(value.cases.map(x=>[x.case_id,x]));
    assert(map.size===d.cases.length, '案例编码重复。');
    const result=emptySession(d);
    if(value.profile) result.profile={...result.profile,...clone(value.profile)};
    result.cases=d.cases.map(c=>{
      const incoming=map.get(c.case_id);assert(incoming,'案例编码缺失。');
      const r={case_id:incoming.case_id,sample_indices:clone(incoming.sample_indices),
        uncertain_intervals_s:clone(incoming.uncertain_intervals_s),note:incoming.note,
        metadata:incoming.metadata===null?null:clone(incoming.metadata),status:incoming.status};
      validateCase(r,c);
      if(r.status==='completed')canComplete(r,c);
      if(incoming.pulse_times_seconds_from_window_onset!==undefined && incoming.pulse_times_seconds_from_window_onset!==null) {
        const times=incoming.pulse_times_seconds_from_window_onset;
        assert(Array.isArray(times) && times.length===r.sample_indices.length &&
          times.every((t,i)=>Number.isFinite(t) && Math.abs(t-timeAt(c,r.sample_indices[i]))<1e-8), '时间与样本索引不一致。');
      }
      return r;
    });
    return result;
  }
  root.PPGAnnotationCore={clone,timeAt,snapIndex,emptyCase,emptySession,validateMetadata,
    mergeRanges,validateCase,canComplete,toExport,fromImport};
})(globalThis);
