import { useLocation } from 'react-router-dom';

export default function Header() {
  const location = useLocation();
  
  const getPageTitle = () => {
    const path = location.pathname;
    if (path === '/') return 'Dashboard Overview';
    if (path.startsWith('/employees')) return 'Employee Directory';
    if (path === '/analytics') return 'Analytics & Reports';
    if (path === '/upload') return 'Data Upload';
    return 'PayRoll Query';
  };

  return (
    <header className="header">
      <div className="header-title">{getPageTitle()}</div>
      <div className="header-actions">
        <span className="badge badge-emerald">System Online</span>
      </div>
    </header>
  );
}
