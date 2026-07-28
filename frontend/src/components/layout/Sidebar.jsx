import { NavLink } from 'react-router-dom';
import { 
  FiHome, 
  FiUsers, 
  FiUploadCloud, 
  FiPieChart, 
  FiLogOut,
  FiBarChart2,
  FiX
} from 'react-icons/fi';

export default function Sidebar({ user, onLogout, isOpen, onClose }) {
  return (
    <aside className={`sidebar ${isOpen ? 'open' : ''}`}>
      <div className="sidebar-brand">
        <div className="sidebar-brand-text">
          <h1>PayRoll Query</h1>
          <p>Analytics Engine</p>
        </div>
        <button className="mobile-close-btn" onClick={onClose}>
          <FiX />
        </button>
      </div>

      <nav className="sidebar-nav">
        <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} end>
          <FiHome className="nav-icon" />
          <span>Dashboard</span>
        </NavLink>
        <NavLink to="/employees" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <FiUsers className="nav-icon" />
          <span>Employees</span>
        </NavLink>
        <NavLink to="/analytics" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <FiPieChart className="nav-icon" />
          <span>Analytics</span>
        </NavLink>
        <NavLink to="/upload" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <FiUploadCloud className="nav-icon" />
          <span>Upload Data</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-user-avatar">
            {user?.full_name?.charAt(0) || 'U'}
          </div>
          <div className="sidebar-user-info">
            <div className="name">{user?.full_name || 'User'}</div>
            <div className="role">{user?.is_admin ? 'Admin' : 'Accountant'}</div>
          </div>
          <button className="logout-btn" onClick={onLogout} title="Logout">
            <FiLogOut />
          </button>
        </div>
      </div>
    </aside>
  );
}
