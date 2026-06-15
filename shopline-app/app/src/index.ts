import express from 'express';
import { join } from 'path';
import shopline from './shopline';
import { readFileSync } from 'fs';
import serveStatic from 'serve-static';
import { webhooksController } from './controller/webhook';
import createProductController from './controller/product/create';

const PORT = parseInt(process.env.BACKEND_PORT || process.env.PORT, 10);

const STATIC_PATH =
  process.env.NODE_ENV === 'production'
    ? `${process.cwd()}/../web/dist`
    : `${process.cwd()}/../web`;

const app = express();

app.get(shopline.config.auth.path, shopline.auth.begin());

app.get(shopline.config.auth.callbackPath, shopline.auth.callback(), shopline.redirectToAppHome());
app.post('/api/webhooks', express.text({ type: '*/*' }), webhooksController());

// api path for frontend/vite.config
app.use('/api/*', express.text({ type: '*/*' }), shopline.validateAuthentication());

app.get('/api/products/create', createProductController);

app.use(express.json());

app.use(shopline.cspHeaders());
app.use(serveStatic(STATIC_PATH, { index: false }));

app.use('/*', shopline.confirmInstallationStatus(), async (_req, res, _next) => {
  return res
    .status(200)
    .set('Content-Type', 'text/html')
    .send(readFileSync(join(STATIC_PATH, 'index.html')));
});

app.listen(PORT);
console.log(PORT);
