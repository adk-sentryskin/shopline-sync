import { RouterProvider } from "react-router-dom";
import { createRouter } from "./Routes";

function App() {
  const pages = import.meta.glob("./pages/**/!(*.test.[jt]sx)*.([jt]sx)", {
    eager: true,
  }) as Record<string, any>;

  return <RouterProvider router={createRouter(pages)} />;
}

export default App;
