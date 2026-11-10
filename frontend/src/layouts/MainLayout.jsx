import { Outlet } from "react-router-dom";

function MainLayout() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white px-8 py-4">
        <h1 className="text-2xl font-bold text-gray-900">
          Resolvix
        </h1>
      </header>

      <main className="p-8">
        <Outlet />
      </main>
    </div>
  );
}

export default MainLayout;