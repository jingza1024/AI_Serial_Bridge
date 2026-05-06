<script setup lang="ts">
import TerminalPanel from './components/TerminalPanel.vue'
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="logo">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14"/>
          <path d="M12 5l7 7-7 7"/>
        </svg>
        <h1>AI Serial Bridge</h1>
      </div>
      <div class="subtitle">AI Agent 串口桥接工具</div>
    </header>
    <main class="app-main">
      <TerminalPanel />
    </main>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background-color: #0d1117;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background-color: #161b22;
  border-bottom: 1px solid #30363d;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #58a6ff;
}

.logo h1 {
  font-size: 18px;
  font-weight: 600;
  color: #e6edf3;
}

.subtitle {
  font-size: 13px;
  color: #8b949e;
}

.app-main {
  flex: 1;
  overflow: hidden;
}
</style>
