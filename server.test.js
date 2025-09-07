const request = require('supertest');
const JSZip = require('jszip');
let app;

beforeEach(() => {
  // fresh instance each test
  jest.resetModules();
  app = require('./server');
});

test('classifier routes sample inputs correctly', async () => {
  const zip = new JSZip();
  zip.file('site_rfi.txt', 'rfi');
  zip.file('safety_photo.jpg', 'safe');
  const buf = await zip.generateAsync({ type: 'nodebuffer' });
  const res = await request(app)
    .post('/api/pm/daily')
    .attach('files', buf, { filename: 'daily.zip' });
  const cats = res.body.uploaded.map(f => f.category);
  expect(cats).toEqual(expect.arrayContaining(['rfis', 'safety']));
});

function binaryParser(res, callback) {
  res.setEncoding('binary');
  let data = '';
  res.on('data', (chunk) => data += chunk);
  res.on('end', () => callback(null, Buffer.from(data, 'binary')));
}

test('compliance pack renders with synthetic data', async () => {
  await request(app).post('/api/pm/daily').attach('files', Buffer.from('prod'), { filename: 'prod_production.txt' });
  const res = await request(app)
    .post('/api/compliance/pack')
    .buffer()
    .parse(binaryParser);
  expect(res.headers['content-type']).toBe('application/zip');
  const zip = await JSZip.loadAsync(res.body);
  expect(Object.keys(zip.files)).toEqual(expect.arrayContaining(['summary.docx', 'summary.pdf']));
});
