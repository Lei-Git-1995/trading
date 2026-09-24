<template>
  <NConfigProvider>
    <NMessageProvider>
      <App />
    </NMessageProvider>
  </NConfigProvider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider } from "naive-ui";
import App from "./App.vue";
</script>

