import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    || (import.meta.env.DEV ? "http://127.0.0.1:8000/api/v1" : `${window.location.origin}/api/v1`),
  timeout: 30000,
});

export function errorMessage(error) {
  return error.response?.data?.detail || error.message || "Unable to reach the EcoPulse API.";
}

export const getDashboard = () => api.get("/dashboard").then((response) => response.data);
export const getForecast = () => api.get("/forecast").then((response) => response.data);
export const getCredits = () => api.get("/credits").then((response) => response.data);
export const getConfig = () => api.get("/config").then((response) => response.data);
export const runSimulation = (parameters) => api.post("/simulate", parameters).then((response) => response.data);
