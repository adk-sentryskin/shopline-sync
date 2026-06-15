import { createBrowserRouter } from 'react-router-dom';
import NotFound from './pages/NotFound';

/**
 *
 * Some examples:
 * * `/pages/index.tsx` matches `/`
 * * * `/pages/Exit-iframe.tsx` matches `/exit-iframe`
 *
 * @param {object} pages Vite supports importing multiple modules from the file system via the special. See https://vitejs.dev/guide/features.html#glob-import
 *
 */
export function getRoutes(pages: Record<string, any>) {
  const routes = Object.keys(pages)
    .map((key) => {
      let path = key
        .replace('./pages', '')
        .replace(/\.(t|j)sx?$/, '')
        .replace(/\/index$/i, '/')
        .replace(/\b[A-Z]/, (firstLetter) => firstLetter.toLowerCase())
        .replace(/\[(?:[.]{3})?(\w+?)\]/g, (_match, param) => `:${param}`);
      if (path.endsWith('/') && path !== '/') {
        path = path.substring(0, path.length - 1);
      }
      if (!pages[key].default) {
        console.error(`${key} doesn't export a default React component`);
      }
      const { default: component, ...rest } = pages[key];
      return {
        path,
        component: component,
        ...rest,
      };
    })
    .filter((route) => route.component);
  return routes;
}
/**
 * use data APIs
 * @link https://reactrouter.com/en/6.22.3/routers/picking-a-router#picking-a-router
 */
export function createRouter(pages: Record<string, any>) {
  const routes = getRoutes(pages);

  const router = createBrowserRouter(
    routes
      .map((v) => ({
        ...v,
        element: <v.component />,
      }))
      .concat({
        path: '*',
        element: <NotFound />,
      } as any),
  );

  return router;
}
