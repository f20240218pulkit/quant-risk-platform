# Institutional Quantitative Risk Platform

A full-stack, cloud-native quantitative finance platform built for portfolio risk analysis, asset allocation, and risk modeling. This platform features a high-performance REST API and an interactive web dashboard for real-time risk calculations.

## 🚀 Key Features

*   **Value at Risk (VaR) Engine:** Calculates Parametric and Historical VaR to estimate potential portfolio downside.
*   **Expected Shortfall (CVaR):** Computes Conditional Value at Risk for tail-risk analysis.
*   **Monte Carlo Simulations:** Projects thousands of potential portfolio trajectories to estimate stochastic risk over multiple time horizons.
*   **Portfolio Optimization (MPT):** Leverages Modern Portfolio Theory to calculate Max Sharpe and Min Variance allocations.
*   **Microservices Architecture:** Decoupled backend (FastAPI) and frontend (Streamlit).
*   **Cloud-Ready:** Fully containerized with Docker, `docker-compose`, and Kubernetes deployment manifests.

## 🛠️ Technology Stack

*   **Backend:** Python 3.10+, FastAPI, Uvicorn, Pydantic
*   **Frontend:** Streamlit
*   **Quantitative Engine:** NumPy, Pandas, SciPy
*   **Testing:** Pytest, HTTPX
*   **DevOps:** Docker, Docker Compose, Kubernetes

## 📦 Local Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/quant-risk-platform.git](https://github.com/yourusername/quant-risk-platform.git)
   cd quant-risk-platform
