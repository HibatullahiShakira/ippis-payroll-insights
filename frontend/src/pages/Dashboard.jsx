import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FiUsers, FiDollarSign, FiFileText, FiTrendingUp } from 'react-icons/fi';
import { analyticsAPI, uploadAPI } from '../api/client';

export default function Dashboard() {
  const [overview, setOverview] = useState(null);
  const [recentUploads, setRecentUploads] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [overviewRes, uploadsRes] = await Promise.all([
          analyticsAPI.monthlyOverview(),
          uploadAPI.list()
        ]);
        
        if (overviewRes.data.months && overviewRes.data.months.length > 0) {
          setOverview(overviewRes.data.months[0]); // Latest month
        }
        
        setRecentUploads(uploadsRes.data.uploads.slice(0, 5));
      } catch (err) {
        console.error("Failed to load dashboard data:", err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
  }, []);

  const formatCurrency = (amount) => {
    if (amount === null || amount === undefined) return '₦0.00';
    return `₦${amount.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  if (loading) {
    return (
      <div className="loading-spinner">
        <div className="spinner"></div>
      </div>
    );
  }

  return (
    <div>
      <div className="card-header">
        <h2 className="header-title">Overview: {overview ? overview.month_year : 'No Data'}</h2>
      </div>

      <div className="stat-cards-grid">
        <div className="stat-card blue">
          <div className="stat-card-icon blue"><FiUsers /></div>
          <div className="stat-card-value">{overview ? overview.employee_count.toLocaleString() : 0}</div>
          <div className="stat-card-label">Total Employees</div>
        </div>
        
        <div className="stat-card emerald">
          <div className="stat-card-icon emerald"><FiDollarSign /></div>
          <div className="stat-card-value">{formatCurrency(overview?.total_net)}</div>
          <div className="stat-card-label">Total Net Payroll</div>
        </div>
        
        <div className="stat-card amber">
          <div className="stat-card-icon amber"><FiTrendingUp /></div>
          <div className="stat-card-value">{formatCurrency(overview?.total_earnings)}</div>
          <div className="stat-card-label">Total Gross Earnings</div>
        </div>
        
        <div className="stat-card rose">
          <div className="stat-card-icon rose"><FiFileText /></div>
          <div className="stat-card-value">{formatCurrency(overview?.total_deductions)}</div>
          <div className="stat-card-label">Total Deductions</div>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header">
          <h3>Recent Uploads</h3>
          <Link to="/upload" className="btn btn-sm btn-ghost">View All</Link>
        </div>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Status</th>
              <th>Records Processed</th>
              <th>Uploaded At</th>
            </tr>
          </thead>
          <tbody>
            {recentUploads.length === 0 ? (
              <tr>
                <td colSpan="4" style={{ textAlign: 'center', padding: '24px' }}>No uploads found</td>
              </tr>
            ) : (
              recentUploads.map(upload => (
                <tr key={upload.id}>
                  <td>{upload.month_year}</td>
                  <td>
                    <span className={`badge ${upload.status === 'completed' ? 'badge-emerald' : upload.status === 'failed' ? 'badge-rose' : 'badge-amber'}`}>
                      {upload.status}
                    </span>
                  </td>
                  <td>{upload.records_processed} / {upload.total_records}</td>
                  <td>{new Date(upload.uploaded_at).toLocaleString()}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
