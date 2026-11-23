<script setup lang="ts">
import type { EvidenceLink } from '@/types/market'
import { linkTitle } from '@/utils/market'

defineProps<{
  links: EvidenceLink[]
  more?: number
}>()
</script>

<template>
  <span v-if="links.length" class="srclist">
    <a
      v-for="link in links"
      :key="link.id"
      class="src"
      :href="link.url"
      target="_blank"
      rel="noopener noreferrer"
      :title="linkTitle(link)"
    >{{ link.id }}</a>
    <span v-if="more" class="src-more">+{{ more }}</span>
  </span>
</template>

<style scoped src="./pane-shared.css"></style>
