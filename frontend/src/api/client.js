/**
 * API client with JWT authentication handling.
 */
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:5000/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 responses (expired/invalid token)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// ── Auth ──
export const authAPI = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  register: (data) => api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
};

// ── Employees ──
export const employeesAPI = {
  list: (params) => api.get('/employees', { params }),
  get: (id) => api.get(`/employees/${id}`),
  history: (id) => api.get(`/employees/${id}/history`),
  departments: () => api.get('/employees/departments'),
  divisions: (department) => api.get('/employees/divisions', { params: { department } }),
  glLevels: () => api.get('/employees/gl-levels'),
};

// ── Payslips ──
export const payslipsAPI = {
  list: (params) => api.get('/payslips', { params }),
  get: (id) => api.get(`/payslips/${id}`),
  getPdfBlob: (id) => api.get(`/payslips/${id}/pdf`, { responseType: 'blob' }),
  months: () => api.get('/payslips/months'),
};

// ── Upload ──
export const uploadAPI = {
  upload: (formData, onProgress) =>
    api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    }),
  list: () => api.get('/uploads'),
  status: (id) => api.get(`/uploads/${id}/status`),
};

// ── Analytics ──
export const analyticsAPI = {
  departmentSummary: (monthYear) => api.get('/analytics/department-summary', { params: { month_year: monthYear } }),
  glDistribution: (monthYear) => api.get('/analytics/gl-distribution', { params: { month_year: monthYear } }),
  deductionBreakdown: (monthYear) => api.get('/analytics/deduction-breakdown', { params: { month_year: monthYear } }),
  salaryTrends: (employeeId) => api.get(`/analytics/salary-trends/${employeeId}`),
  monthlyOverview: () => api.get('/analytics/monthly-overview'),
};

// ── Export ──
export const exportAPI = {
  employeesCSV: (params) =>
    api.get('/export/employees', { params, responseType: 'blob' }),
  payslipsCSV: (params) =>
    api.get('/export/payslips', { params, responseType: 'blob' }),
  bulkPayslipsPDF: (params) =>
    api.get('/export/bulk-payslips', { params, responseType: 'blob' }),
  employeeBulkPayslipsPDF: (params) =>
    api.get('/export/employee-bulk-payslips', { params, responseType: 'blob' }),
};

export default api;
