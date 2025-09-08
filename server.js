const express = require('express');
const multer = require('multer');
const JSZip = require('jszip');
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun } = require('docx');
const PDFDocument = require('pdfkit');
const path = require('path');
const app = express();
const upload = multer({ storage: multer.memoryStorage() });

app.use(express.json());

// In-memory data store
const store = {
  dailyLogs: [],
  rfis: [],
  submittals: [],
  safety: [],
  activities: []
};

const categories = {
  rfi: 'rfis',
  submittal: 'submittals',
  delivery: 'deliveries',
  production: 'production',
  equipment: 'equipment',
  safety: 'safety'
};

function classifyFile(name) {
  const lower = name.toLowerCase();
  for (const key of Object.keys(categories)) {
    if (lower.includes(key)) return categories[key];
  }
  return 'other';
}

app.post('/api/pm/daily', upload.any(), async (req, res) => {
  const files = [];
  for (const file of req.files) {
    if (file.originalname.endsWith('.zip')) {
      const zip = await JSZip.loadAsync(file.buffer);
      for (const filename of Object.keys(zip.files)) {
        const cat = classifyFile(filename);
        files.push({ filename, category: cat });
        store.dailyLogs.push({ filename, category: cat, date: new Date() });
      }
    } else {
      const cat = classifyFile(file.originalname);
      files.push({ filename: file.originalname, category: cat });
      store.dailyLogs.push({ filename: file.originalname, category: cat, date: new Date() });
    }
  }
  res.json({ uploaded: files });
});

app.get('/api/pm/summary', (req, res) => {
  const projectId = req.query.projectId || 'default';
  const byCat = {};
  for (const log of store.dailyLogs) {
    byCat[log.category] = (byCat[log.category] || 0) + 1;
  }
  const EV = byCat['production'] || 0;
  const PV = store.activities.length || 1;
  const AC = (byCat['production'] || 0) + (byCat['delivery'] || 0);
  const CPI = AC ? EV / AC : 0;
  const SPI = PV ? EV / PV : 0;
  res.json({ projectId, categories: byCat, earnedValue: { CPI, SPI } });
});

async function createDocx(summary) {
  const doc = new Document({
    sections: [
      {
        children: [
          new Paragraph({ children: [new TextRun('Compliance Summary')] }),
          new Paragraph(JSON.stringify(summary))
        ]
      }
    ]
  });
  return await Packer.toBuffer(doc);
}

async function createPdf(summary) {
  const doc = new PDFDocument();
  const chunks = [];
  doc.on('data', (c) => chunks.push(c));
  doc.text('Compliance Summary');
  doc.text(JSON.stringify(summary));
  doc.end();
  return await new Promise((resolve) => {
    doc.on('end', () => resolve(Buffer.concat(chunks)));
  });
}

app.post('/api/compliance/pack', async (req, res) => {
  const summary = { logs: store.dailyLogs.length, rfis: store.rfis.length };
  const [docxBuffer, pdfBuffer] = await Promise.all([
    createDocx(summary),
    createPdf(summary)
  ]);
  const zip = new JSZip();
  zip.file('summary.docx', docxBuffer);
  zip.file('summary.pdf', pdfBuffer);
  const buf = await zip.generateAsync({ type: 'nodebuffer' });
  res.set('Content-Type', 'application/zip');
  res.send(buf);
});

function requireRole(roles) {
  return (req, res, next) => {
    const role = req.headers['x-role'] || 'viewer';
    if (!roles.includes(role)) return res.status(403).send('Forbidden');
    next();
  };
}

function crudRouter(collectionName) {
  const router = express.Router();
  router.get('/', (req, res) => {
    res.json(store[collectionName]);
  });
  router.post('/', requireRole(['admin', 'pm']), (req, res) => {
    const item = { id: Date.now().toString(), ...req.body };
    store[collectionName].push(item);
    res.status(201).json(item);
  });
  router.put('/:id', requireRole(['admin', 'pm']), (req, res) => {
    const idx = store[collectionName].findIndex((i) => i.id === req.params.id);
    if (idx === -1) return res.status(404).send('Not found');
    store[collectionName][idx] = { ...store[collectionName][idx], ...req.body };
    res.json(store[collectionName][idx]);
  });
  router.delete('/:id', requireRole(['admin', 'pm']), (req, res) => {
    const idx = store[collectionName].findIndex((i) => i.id === req.params.id);
    if (idx === -1) return res.status(404).send('Not found');
    const removed = store[collectionName].splice(idx, 1);
    res.json(removed[0]);
  });
  return router;
}

app.use('/api/rfis', crudRouter('rfis'));
app.use('/api/submittals', crudRouter('submittals'));
app.use('/api/safety', crudRouter('safety'));
app.use('/api/activities', crudRouter('activities'));

// simple UI
app.use(express.static(path.join(__dirname, 'public')));

if (require.main === module) {
  const port = process.env.PORT || 3000;
  app.listen(port, () => console.log(`Server running on ${port}`));
}

module.exports = app;
