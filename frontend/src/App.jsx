import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import AuthProvider from "./context/AuthProvider";
import AdminLayout from "./layouts/AdminLayout";
import MainLayout from "./layouts/MainLayout";
import Chat from "./pages/Chat";
import Login from "./pages/Login";
import AdminAiTest from "./pages/admin/AdminAiTest";
import AdminConversations from "./pages/admin/AdminConversations";
import AdminDocuments from "./pages/admin/AdminDocuments";
import AdminFaqs from "./pages/admin/AdminFaqs";
import AdminOrders from "./pages/admin/AdminOrders";
import AdminOverview from "./pages/admin/AdminOverview";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<MainLayout />}>
              <Route index element={<Chat />} />
            </Route>
          </Route>

          <Route element={<ProtectedRoute requireAdmin />}>
            <Route path="/admin" element={<AdminLayout />}>
              <Route index element={<AdminOverview />} />
              <Route path="faqs" element={<AdminFaqs />} />
              <Route path="documents" element={<AdminDocuments />} />
              <Route path="orders" element={<AdminOrders />} />
              <Route path="conversations" element={<AdminConversations />} />
              <Route path="ai" element={<AdminAiTest />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
