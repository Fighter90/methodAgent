import { defineConfig } from 'vitest/config'

// Юнит-тесты интерфейса (ТЗ 4.11, T-23): jsdom вместо браузера, без сети
export default defineConfig({
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'], restoreMocks: true },
})
