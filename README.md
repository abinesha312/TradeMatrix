# MiView Dashboard

A real-time market data and trading insights dashboard.

## Deployment Instructions

### Deploying to Vercel

1. Install the Vercel CLI:

```bash
npm install -g vercel
```

2. Login to Vercel:

```bash
vercel login
```

3. Deploy the project:

```bash
vercel
```

### Manual Deployment

1. Install dependencies:

```bash
npm install
```

2. Start the development server:

```bash
npm start
```

## Project Structure

- `templates/index.html` - Main application file
- `vercel.json` - Vercel deployment configuration
- `package.json` - Project dependencies and scripts

## Features

- Real-time market data visualization
- Oil price tracking
- FX rates monitoring
- Interactive charts
- Chat interface for data queries

## 1. Clone and install

```bash
git clone https://github.com/youruser/miview-lite.git
cd miview-lite/backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your API keys
cd ../frontend && npm install
```
