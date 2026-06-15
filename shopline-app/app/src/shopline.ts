import { shoplineApp } from '@shoplineos/shopline-app-express';
import { SQLiteSessionStorage } from '@shoplineos/shopline-app-session-storage-sqlite';
import 'dotenv/config';

const DB_PATH = `${process.cwd()}/database.sqlite`;

const shopline = shoplineApp({
  appKey: process.env.SHOPLINE_APP_KEY || '',
  appSecret: process.env.SHOPLINE_APP_SECRET || '',
  appUrl: process.env.SHOPLINE_APP_URL || '',
  authPathPrefix: '/api/auth',
  scopes: process.env.SCOPES?.split(',') || [],
  sessionStorage: new SQLiteSessionStorage(DB_PATH),
  isEmbeddedApp: true,
  webhooks: {
    'apps/installed_uninstalled': {
      callbackUrl: '/api/webhooks',
    },
  },
  hooks: {
    afterAuth: async ({ session }) => {
      shopline.registerWebhooks({ session });
    },
  },
});

export default shopline;
