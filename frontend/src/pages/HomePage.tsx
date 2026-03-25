import { useState } from 'react'
import { motion } from 'framer-motion'
import { DeveloperLinks } from '../components/DeveloperLinks'
import { PageSEO } from '../components/PageSEO'
import { UnifiedSearchBox } from '../components/UnifiedSearchBox'
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE } from '../lib/seo'

export default function HomePage() {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)

  return (
    <>
      <PageSEO
        title={DEFAULT_TITLE}
        description={DEFAULT_DESCRIPTION}
        path="/"
      />

      {/* Red left stripe */}
      <div className="fixed left-0 top-0 z-50 h-full w-[6px] bg-[#CC1100]" />

      {/* Geometric background accents */}
      <div
        className="pointer-events-none fixed right-[-60px] top-[-80px] z-0 h-[340px] w-[260px] bg-[#CC1100]"
        style={{ opacity: 0.08 }}
      />
      <div
        className="pointer-events-none fixed bottom-10 right-20 z-0 h-36 w-10 bg-[#F5C400]"
        style={{ opacity: 0.6 }}
      />

      {/* Main content */}
      <div className="relative z-10 flex min-h-screen flex-col items-center justify-start px-6 pl-10 pt-[22vh]">
        <motion.div
          className="flex w-full max-w-[560px] flex-col items-center"
          animate={{ y: isDropdownOpen ? -56 : 0 }}
          transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
        >
          {/* Wordmark — w-fit so the rule matches text width, not the search box */}
          <div className="mb-10 w-fit animate-[fadeIn_0.4s_ease-out] text-center">
            <h1
              className="font-display font-[900] uppercase leading-[0.92] tracking-[-0.02em] text-[#111111]"
              style={{ fontSize: 'clamp(64px, 12vw, 108px)' }}
            >
              Oracle<br />Tutor
            </h1>
            <div className="my-[14px] h-[2px] w-full bg-[#111111]" />
            <p className="font-mono text-[13px] text-[#7A7670]">
              find cards by meaning, not keywords.
            </p>
          </div>

          {/* Unified search */}
          <div
            className="w-full animate-[slideUp_0.4s_ease-out_0.15s] opacity-0"
            style={{ animationFillMode: 'forwards' }}
          >
            <UnifiedSearchBox autoFocus onDropdownChange={setIsDropdownOpen} />
          </div>
        </motion.div>

        {/* Developer links */}
        <div className="fixed bottom-5 left-10">
          <DeveloperLinks variant="dark" />
        </div>
      </div>
    </>
  )
}
