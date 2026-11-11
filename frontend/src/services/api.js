import axios from "axios";

const API_ACCESS_TOKEN_KEY = "ecopulse-api-access-token";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    || (import.meta.env.DEV ? "http://127.0.0.1:8000/api/v1" : `${window.location.origin}/api/v1`),
  timeout: 30000,
});

api.interceptors.request.use((request) => {
  const token = window.sessionStorage.getItem(API_ACCESS_TOKEN_KEY);
  if (token) request.headers.Authorization = `Bearer ${token}`;
  return request;
});

export function getApiAccessToken() {
  return window.sessionStorage.getItem(API_ACCESS_TOKEN_KEY) || "";
}

export function setApiAccessToken(token) {
  const value = token.trim();
  if (value) window.sessionStorage.setItem(API_ACCESS_TOKEN_KEY, value);
  else window.sessionStorage.removeItem(API_ACCESS_TOKEN_KEY);
}

export function errorMessage(error) {
  return error.response?.data?.detail || error.message || "Unable to reach the EcoPulse API.";
}

export const getDashboard = () => api.get("/dashboard").then((response) => response.data);
export const getForecast = () => api.get("/forecast").then((response) => response.data);
export const getCredits = () => api.get("/credits").then((response) => response.data);
export const getConfig = () => api.get("/config").then((response) => response.data);
export const runSimulation = (parameters) => api.post("/simulate", parameters).then((response) => response.data);
export const getEnergyIntelligence = (location) =>
  api.get("/intelligence/overview", { params: { location } }).then((response) => response.data);
export const getEnergyResearch = (topic) =>
  api.get("/intelligence/research", { params: { topic } }).then((response) => response.data);
export const searchWeatherLocations = (query) =>
  api.get("/intelligence/weather/search", { params: { query } }).then((response) => response.data);
export const askEnergyAdvisor = (question, researchTopic) =>
  api.post("/advisor", { question, research_topic: researchTopic || null }).then((response) => response.data);
