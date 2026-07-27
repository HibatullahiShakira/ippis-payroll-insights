import { useState, useEffect } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { analyticsAPI, payslipsAPI } from '../api/client';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#06b6d4', '#84cc16'];

export default function Analytics() {
  const [months, setMonths] = useState([]);
  const [selectedMonth, setSelectedMonth] = useState('');
  
  const [deptData, setDeptData] = useState([]);
  const [glData, setGlData] = useState([]);
  const [deductionData, setDeductionData] = useState([]);
  const [loading, setLoading] = useState(true);

  // Load available months
  useEffect(() => {
    const fetchMonths = async () => {
      try {
        const res = await payslipsAPI.months();
        if (res.data.months && res.data.months.length > 0) {
          setMonths(res.data.months);
          setSelectedMonth(res.data.months[0]);
        } else {
          setLoading(false);
        }
      } catch (err) {
        console.error("Failed to load months:", err);
        setLoading(false);
      }
    };
    fetchMonths();
  }, []);

  // Load analytics when month changes
  useEffect(() => {
    if (!selectedMonth) return;

    const fetchAnalytics = async () => {
      setLoading(true);
      try {
        const [deptRes, glRes, dedRes] = await Promise.all([
          analyticsAPI.departmentSummary(selectedMonth),
          analyticsAPI.glDistribution(selectedMonth),
          analyticsAPI.deductionBreakdown(selectedMonth)
        ]);
        
        setDeptData(deptRes.data.departments.slice(0, 10)); // Top 10 depts
        setGlData(glRes.data.gl_levels);
        setDeductionData(dedRes.data.deductions.slice(0, 10)); // Top 10 deductions
        
      } catch (err) {
        console.error("Failed to load analytics:", err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchAnalytics();
  }, [selectedMonth]);

  const formatCurrency = (value) => {
    if (value >= 1000000) return `₦${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `₦${(value / 1000).toFixed(1)}K`;
    return `₦${value}`;
  };

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-secondary)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
          <p style={{ fontWeight: 600, marginBottom: '8px' }}>{label}</p>
          {payload.map((entry, index) => (
            <div key={index} style={{ color: entry.color, fontSize: '0.85rem' }}>
              {entry.name}: {entry.name.includes('Amount') || entry.name.includes('Net') ? 
                `₦${entry.value.toLocaleString()}` : 
                entry.value.toLocaleString()}
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  if (!selectedMonth && !loading) {
    return <div className="empty-state">No data available. Please upload payroll data first.</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h2 className="header-title">Analytics Dashboard</h2>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <select 
            className="form-select" 
            value={selectedMonth} 
            onChange={(e) => setSelectedMonth(e.target.value)}
            style={{ width: '200px' }}
          >
            {months.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="loading-spinner"><div className="spinner"></div></div>
      ) : (
        <>
          <div className="charts-grid">
            {/* Department Summary */}
            <div className="card">
              <h3 className="chart-card-title">Top 10 Departments by Payroll Cost</h3>
              <div style={{ height: 350 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={deptData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-secondary)" horizontal={false} />
                    <XAxis type="number" tickFormatter={formatCurrency} stroke="var(--text-muted)" />
                    <YAxis dataKey="department" type="category" width={120} stroke="var(--text-muted)" fontSize={11} tick={{ fill: 'var(--text-muted)' }} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend />
                    <Bar dataKey="total_net" name="Total Net Pay" fill="var(--accent-blue)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Deduction Breakdown */}
            <div className="card">
              <h3 className="chart-card-title">Top 10 Deductions</h3>
              <div style={{ height: 350 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={deductionData} margin={{ top: 5, right: 30, left: 20, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-secondary)" vertical={false} />
                    <XAxis dataKey="deduction_type" stroke="var(--text-muted)" fontSize={10} angle={-45} textAnchor="end" height={60} />
                    <YAxis tickFormatter={formatCurrency} stroke="var(--text-muted)" />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="total_amount" name="Total Amount" fill="var(--accent-rose)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="chart-card-title">Grade Level (GL) Distribution</h3>
            <div style={{ height: 350, display: 'flex' }}>
              <div style={{ flex: 1 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={glData}
                      cx="50%"
                      cy="50%"
                      innerRadius={80}
                      outerRadius={120}
                      paddingAngle={2}
                      dataKey="headcount"
                      nameKey="gl"
                      label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                    >
                      {glData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                <table style={{ background: 'transparent' }}>
                  <thead>
                    <tr>
                      <th style={{ background: 'transparent' }}>GL</th>
                      <th style={{ background: 'transparent' }}>Headcount</th>
                      <th style={{ background: 'transparent' }}>Avg Earnings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {glData.map((item, i) => (
                      <tr key={item.gl}>
                        <td>
                          <span style={{ 
                            display: 'inline-block', width: '12px', height: '12px', 
                            backgroundColor: COLORS[i % COLORS.length], marginRight: '8px', borderRadius: '2px'
                          }}></span>
                          {item.gl}
                        </td>
                        <td>{item.headcount}</td>
                        <td>{formatCurrency(item.avg_earnings)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
