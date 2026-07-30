import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiSearch, FiDownload, FiFilter } from 'react-icons/fi';
import { employeesAPI, payslipsAPI, exportAPI } from '../api/client';

export default function Employees() {
  const navigate = useNavigate();
  const [employees, setEmployees] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, per_page: 25, total: 0, pages: 0 });
  const [loading, setLoading] = useState(true);
  
  const [filters, setFilters] = useState({
    search: '',
    department: '',
    division: '',
    gl: ''
  });
  
  const [dropdowns, setDropdowns] = useState({ departments: [], divisions: [], glLevels: [], months: [] });
  const [bulkExportMonth, setBulkExportMonth] = useState('');

  // Load dropdown data
  useEffect(() => {
    const fetchDropdowns = async () => {
      try {
        const [deptRes, divRes, glRes, monthsRes] = await Promise.all([
          employeesAPI.departments(),
          employeesAPI.divisions(filters.department),
          employeesAPI.glLevels(),
          payslipsAPI.months()
        ]);
        setDropdowns({
          departments: deptRes.data.departments,
          divisions: divRes.data.divisions,
          glLevels: glRes.data.gl_levels,
          months: monthsRes.data.months
        });
        if (monthsRes.data.months.length > 0) {
          setBulkExportMonth(monthsRes.data.months[0]);
        }
      } catch (err) {
        console.error("Failed to load dropdowns:", err);
      }
    };
    fetchDropdowns();
  }, [filters.department]);

  // Load employees
  useEffect(() => {
    fetchEmployees();
  }, [pagination.page, filters]);

  const fetchEmployees = async () => {
    setLoading(true);
    try {
      const res = await employeesAPI.list({
        page: pagination.page,
        per_page: pagination.per_page,
        ...filters
      });
      setEmployees(res.data.employees);
      setPagination(res.data.pagination);
    } catch (err) {
      console.error("Failed to load employees:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setFilters(prev => ({ ...prev, [name]: value }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const handleGlMultiChange = (e) => {
    const options = e.target.options;
    const selectedValues = [];
    for (let i = 0; i < options.length; i++) {
      if (options[i].selected) {
        selectedValues.push(options[i].value);
      }
    }
    setFilters(prev => ({ ...prev, gl: selectedValues.join(',') }));
    setPagination(prev => ({ ...prev, page: 1 }));
  };

  const handleExport = async () => {
    try {
      const res = await exportAPI.employeesCSV(filters);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'employees_export.csv');
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      console.error("Export failed:", err);
    }
  };

  const handleBulkExportPdf = async () => {
    if (!bulkExportMonth) {
      alert("Please select a month to export payslips for.");
      return;
    }
    try {
      const res = await exportAPI.bulkPayslipsPDF({ ...filters, month_year: bulkExportMonth });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `Bulk_Payslips_${bulkExportMonth}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      console.error("Bulk PDF Export failed:", err);
      alert("Failed to export bulk payslips. Ensure there are payslips for the selected month.");
    }
  };

  return (
    <div>
      <div className="filter-panel">
        <div className="filter-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <h3><FiFilter /> Filters & Search</h3>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <button className="btn btn-sm btn-secondary" onClick={handleExport}>
              <FiDownload /> Export CSV
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'var(--bg-secondary)', padding: '2px', borderRadius: 'var(--radius-md)' }}>
              <select 
                className="form-select" 
                style={{ padding: '4px 8px', fontSize: '0.85rem', width: 'auto', border: 'none', background: 'transparent' }}
                value={bulkExportMonth}
                onChange={(e) => setBulkExportMonth(e.target.value)}
              >
                {dropdowns.months.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <button className="btn btn-sm btn-primary" onClick={handleBulkExportPdf}>
                <FiDownload /> Bulk PDF Payslips
              </button>
            </div>
          </div>
        </div>
        
        <div className="filter-grid">
          <div className="form-group">
            <label className="form-label">Search (Name / File No / IPPIS)</label>
            <div className="search-bar" style={{ maxWidth: '100%' }}>
              <FiSearch className="search-icon" />
              <input 
                type="text" 
                name="search"
                value={filters.search}
                onChange={handleFilterChange}
                placeholder="Search..."
              />
            </div>
          </div>
          
          <div className="form-group">
            <label className="form-label">Department</label>
            <select name="department" className="form-select" value={filters.department} onChange={handleFilterChange}>
              <option value="">All Departments</option>
              {dropdowns.departments.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          
          <div className="form-group">
            <label className="form-label">Division</label>
            <select name="division" className="form-select" value={filters.division} onChange={handleFilterChange}>
              <option value="">All Divisions</option>
              {dropdowns.divisions.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          
          <div className="form-group">
            <label className="form-label">Grade Level (GL) - Hold Ctrl to select multiple</label>
            <select 
              name="gl" 
              className="form-select" 
              multiple 
              size="3"
              style={{ minHeight: '80px' }}
              value={filters.gl ? filters.gl.split(',') : []} 
              onChange={handleGlMultiChange}
            >
              {dropdowns.glLevels.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header">
          <h3>Employees ({pagination.total})</h3>
        </div>
        
        {loading ? (
          <div className="loading-spinner"><div className="spinner"></div></div>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>S/NO</th>
                  <th>File No</th>
                  <th>IPPIS Number</th>
                  <th>Name</th>
                  <th>GL</th>
                  <th>Department</th>
                  <th>Division</th>
                </tr>
              </thead>
              <tbody>
                {employees.length === 0 ? (
                  <tr><td colSpan="7" style={{ textAlign: 'center', padding: '24px' }}>No employees found</td></tr>
                ) : (
                  employees.map(emp => (
                    <tr key={emp.id} onClick={() => navigate(`/employees/${emp.id}`)}>
                      <td>{emp.id}</td>
                      <td>{emp.file_no}</td>
                      <td>{emp.ippis_number}</td>
                      <td style={{ fontWeight: 600 }}>{emp.name}</td>
                      <td>{emp.gl}</td>
                      <td>{emp.department}</td>
                      <td>{emp.division}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            
            {/* Pagination Controls */}
            {pagination.pages > 1 && (
              <div className="pagination">
                <div className="pagination-info">
                  Showing {(pagination.page - 1) * pagination.per_page + 1} to {Math.min(pagination.page * pagination.per_page, pagination.total)} of {pagination.total}
                </div>
                <div className="pagination-controls">
                  <button 
                    className="pagination-btn" 
                    disabled={!pagination.has_prev}
                    onClick={() => setPagination(prev => ({ ...prev, page: prev.page - 1 }))}
                  >
                    Previous
                  </button>
                  <span style={{ fontSize: '0.8rem', margin: '0 8px' }}>Page {pagination.page} of {pagination.pages}</span>
                  <button 
                    className="pagination-btn" 
                    disabled={!pagination.has_next}
                    onClick={() => setPagination(prev => ({ ...prev, page: prev.page + 1 }))}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
