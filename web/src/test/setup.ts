import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount each test's render (automatic only with Vitest globals, which aren't on).
afterEach(cleanup)
