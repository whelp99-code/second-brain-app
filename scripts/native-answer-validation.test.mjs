import assert from 'node:assert/strict';
import test from 'node:test';
import { parseInsufficientEvidenceAnswer as parse } from './native-answer-validation.mjs';
const valid = JSON.stringify({status:'insufficient_evidence',value:null,explanation:'The returned records contain no address.'});
test('accept complete JSON or one fenced JSON including CRLF and trailing whitespace', () => {
  for (const text of [valid, '```json\n'+valid+'\n```', '```json\r\n'+valid+'\r\n```  \n']) {
    assert.equal(parse(text).value,null);
    assert.equal(parse(text).raw_response,text.trim());
  }
});
test('reject contradictory prose and additional blocks instead of dropping them', () => {
  for (const text of ['The IP is 192.0.2.1.\n```json\n'+valid+'\n```',
    '```json\n'+valid+'\n```\nThe IP is 192.0.2.1.',
    '```json\n'+valid+'\n```\n```json\n{}\n```']) assert.throws(()=>parse(text));
});
test('reject unsupported statuses, values and extra fields', () => {
  const base=JSON.parse(valid);
  for (const value of [null,[],{...base,value:'192.0.2.1'},{...base,status:'supported'},
    {...base,explanation:''},{...base,ip:'192.0.2.1'}]) assert.throws(()=>parse(JSON.stringify(value)));
});

test('supported evidence must match the gold value; blanket abstention and wrong facts fail', async () => {
  const {parseSupportedEvidenceAnswer: supported} = await import('./native-answer-validation.mjs');
  const answer={status:'supported',value:'첫 결정',explanation:'The record text states this.'};
  assert.equal(supported(JSON.stringify(answer),'첫 결정').value,'첫 결정');
  assert.throws(()=>supported(valid,'첫 결정'));
  assert.throws(()=>supported(JSON.stringify({...answer,value:'두 번째 결정'}),'첫 결정'));
});
