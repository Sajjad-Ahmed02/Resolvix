import { Outlet } from "react-router-dom";

function MainLayout() {
  return (
    <div className="min-h-dvh bg-stone-100 text-stone-900">
      <Outlet />
    </div>
  );
}

export default MainLayout;
