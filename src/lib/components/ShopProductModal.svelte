<script lang="ts">
	/**
	 * The product page, as a dialog.
	 *
	 * A separate `/shop/[id]` route would need explicit `entries()` (the site is
	 * client-rendered, so the prerenderer cannot crawl to a page whose ids live
	 * in a runtime JSON) and would put a navigation between wanting a product and
	 * buying it. One dialog over the grid keeps the buy button one click away
	 * from every product, and the catalog stays a data file.
	 *
	 * Same shell as `HskDeckModal` / `RadicalDeckModal`: backdrop click and Esc
	 * both close.
	 */
	import {
		buyUrl,
		formatPrice,
		freeHref,
		isUnpriced,
		priceUnit,
		productImage,
		tileGlyph,
		type ShopManifest,
		type ShopProduct
	} from '$lib/shop';
	import { btnPrimary, btnSecondary } from '$lib/buttonStyles';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Check from '@lucide/svelte/icons/check';
	import ShoppingBag from '@lucide/svelte/icons/shopping-bag';
	import X from '@lucide/svelte/icons/x';

	let {
		manifest,
		product,
		onClose
	}: { manifest: ShopManifest; product: ShopProduct; onClose: () => void } = $props();

	let failed = $state(false);

	const src = $derived(productImage(product));
	const href = $derived(buyUrl(manifest, product));
	const free = $derived(freeHref(product));
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div
	class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-5"
	role="presentation"
	onclick={(e) => e.target === e.currentTarget && onClose()}
>
	<div
		class="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-2xl bg-white p-6 shadow-xl sm:rounded-2xl"
		role="dialog"
		aria-modal="true"
		aria-label={product.name}
	>
		<div class="flex items-start justify-between gap-4">
			<div>
				{#if product.badge}
					<span
						class="mb-2 inline-block rounded-full bg-neutral-900 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-white"
					>
						{product.badge}
					</span>
				{/if}
				<h2 class="text-xl font-bold tracking-tight">{product.name}</h2>
				<p class="mt-1 text-sm text-neutral-500">{product.tagline}</p>
			</div>
			<button
				onclick={onClose}
				aria-label="Close"
				class="rounded-md p-1.5 text-neutral-400 transition hover:bg-neutral-100 hover:text-neutral-900"
			>
				<X size={18} />
			</button>
		</div>

		<div class="mt-5 overflow-hidden rounded-xl border border-neutral-200 bg-neutral-50">
			{#if src && !failed}
				<img
					{src}
					alt={product.imageAlt || product.name}
					onerror={() => (failed = true)}
					class="max-h-[38vh] w-full object-cover object-top"
				/>
			{:else}
				<div
					class="flex h-44 w-full items-center justify-center bg-gradient-to-br from-neutral-100 to-neutral-200"
				>
					<span class="text-6xl font-light text-neutral-400" lang="zh-Hans">
						{tileGlyph(product)}
					</span>
				</div>
			{/if}
		</div>

		<p class="mt-5 text-sm leading-relaxed text-neutral-700">{product.description}</p>

		{#if product.highlights?.length}
			<h3 class="mt-6 font-mono text-[11px] uppercase tracking-[0.2em] text-neutral-400">
				What is in it
			</h3>
			<ul class="mt-3 space-y-2">
				{#each product.highlights as line (line)}
					<li class="flex gap-2.5 text-sm text-neutral-700">
						<Check size={15} class="mt-0.5 shrink-0 text-neutral-900" />
						<span>{line}</span>
					</li>
				{/each}
			</ul>
		{/if}

		{#if product.specs?.length}
			<div class="mt-6 overflow-hidden rounded-xl border border-neutral-200">
				<table class="w-full text-sm">
					<tbody>
						{#each product.specs as spec (spec.label)}
							<tr class="border-b border-neutral-100 last:border-0">
								<td
									class="w-40 bg-neutral-50 px-4 py-2.5 font-mono text-[11px] uppercase tracking-wider text-neutral-400"
								>
									{spec.label}
								</td>
								<td class="px-4 py-2.5 text-neutral-700">{spec.value}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		{#if free}
			<p class="mt-5 text-xs text-neutral-400">
				There is a free version of this on the site —
				<a href={free} onclick={onClose} class="underline">{product.freeAlternative?.label}</a>. The
				paid edition is what funds it.
			</p>
		{/if}

		<div class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-5">
			<div class="flex items-baseline gap-1.5">
				<span
					class={isUnpriced(product.price)
						? 'text-sm font-medium text-neutral-500'
						: 'text-2xl font-bold tracking-tight'}
				>
					{formatPrice(product.price, manifest.currency)}
				</span>
				{#if priceUnit(product.price)}
					<span class="font-mono text-xs uppercase tracking-wider text-neutral-400">
						{priceUnit(product.price)}
					</span>
				{/if}
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<button type="button" class={btnSecondary} onclick={onClose}>Close</button>
				<a
					class="{btnPrimary} inline-flex items-center gap-2"
					{href}
					target="_blank"
					rel="noopener noreferrer"
				>
					<ShoppingBag size={15} /> Buy on Patreon
					<ArrowUpRight size={14} />
				</a>
			</div>
		</div>
	</div>
</div>
