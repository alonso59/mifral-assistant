<script lang="ts">
  import { ChevronDown, ChevronUp, BookOpen } from 'lucide-svelte';

  interface CitationChunk {
    title: string;
    section?: string | null;
    page?: number | null;
    excerpt: string;
  }

  export let chunks: CitationChunk[] = [];

  let open = false;

  function toggle() {
    open = !open;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  }
</script>

<div class="text-[10.5px] text-black/40">
  <!-- Toggle trigger — keyboard accessible -->
  <div
    role="button"
    tabindex="0"
    class="flex cursor-pointer items-center gap-1 select-none hover:text-black/60 transition-colors"
    on:click={toggle}
    on:keydown={handleKeydown}
  >
    <BookOpen class="h-3 w-3 flex-shrink-0" strokeWidth={1.5} />
    <span>View sources ({chunks.length})</span>
    {#if open}
      <ChevronUp class="h-3 w-3" strokeWidth={1.5} />
    {:else}
      <ChevronDown class="h-3 w-3" strokeWidth={1.5} />
    {/if}
  </div>

  {#if open}
    <div class="mt-1.5 space-y-1.5 rounded-lg border border-black/[0.06] bg-white/60 p-2">
      {#each chunks as chunk, i (i)}
        <div class="border-b border-black/[0.04] pb-1.5 last:border-0 last:pb-0">
          <p class="font-medium text-black/55" style="font-weight: 550;">
            [{i + 1}] {chunk.title}{#if chunk.section} — {chunk.section}{/if}{#if chunk.page != null} (p.{chunk.page}){/if}
          </p>
          <p class="mt-0.5 leading-relaxed text-black/35 line-clamp-2">{chunk.excerpt}</p>
        </div>
      {/each}
    </div>
  {/if}
</div>
