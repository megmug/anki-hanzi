import { describe, expect, it } from 'vitest';
import {
	buyUrl,
	currencySymbol,
	formatPrice,
	freeHref,
	isUnpriced,
	priceUnit,
	productImage,
	tileGlyph,
	visibleProducts,
	type ShopManifest,
	type ShopProduct,
} from './shop';

const product = (over: Partial<ShopProduct> = {}): ShopProduct => ({
	id: 'kangxi-radicals',
	name: 'The 214 Kangxi radicals',
	tagline: 'Every radical.',
	price: { amount: 9 },
	buyUrl: 'https://www.patreon.com/krmani/posts/kangxi-radicals-166891672',
	description: '',
	highlights: [],
	...over,
});

const manifest: ShopManifest = {
	generated: '2026-09-08',
	currency: 'USD',
	shop: 'https://www.patreon.com/cw/krmani/shop',
	products: [],
};

describe('formatPrice', () => {
	it('drops the cents on a whole amount', () => {
		expect(formatPrice({ amount: 12 })).toBe('$12');
	});

	it('keeps two decimals on a fractional one', () => {
		expect(formatPrice({ amount: 12.5 })).toBe('$12.50');
	});

	it('takes the product currency over the manifest default', () => {
		expect(formatPrice({ amount: 8, currency: 'EUR' }, 'USD')).toBe('€8');
	});

	// A placeholder must never render as "$0" — a paid deck reading free is
	// worse than no number at all.
	it('sends a zero, missing or negative amount to Patreon', () => {
		expect(formatPrice({ amount: 0 })).toBe('See price on Patreon');
		expect(formatPrice(undefined)).toBe('See price on Patreon');
		expect(formatPrice({ amount: -3 })).toBe('See price on Patreon');
	});

	it('falls back to the ISO code for an unknown currency', () => {
		expect(formatPrice({ amount: 5, currency: 'JPY' })).toBe('JPY 5');
		expect(currencySymbol('gbp')).toBe('£');
	});
});

describe('isUnpriced / priceUnit', () => {
	it('reads a zero amount as unpriced', () => {
		expect(isUnpriced({ amount: 0 })).toBe(true);
		expect(isUnpriced({ amount: 1 })).toBe(false);
	});

	// The unit qualifies a number; with no number it qualifies nothing.
	it('hides the unit while the product is unpriced', () => {
		expect(priceUnit({ amount: 0, unit: 'per level' })).toBe('');
		expect(priceUnit({ amount: 12, unit: 'per level' })).toBe('per level');
		expect(priceUnit({ amount: 12 })).toBe('');
	});
});

describe('visibleProducts', () => {
	// A product still being built keeps its copy in the catalog and stays off the
	// page, so shipping it later is a one-word edit rather than a rewrite.
	it('drops the hidden ones', () => {
		const products = [product({ id: 'a' }), product({ id: 'b', hidden: true })];
		expect(visibleProducts({ ...manifest, products }).map((p) => p.id)).toEqual(['a']);
	});

	it('is empty with no manifest', () => {
		expect(visibleProducts(null)).toEqual([]);
	});
});

describe('links', () => {
	it('buys at the product post when there is one', () => {
		expect(buyUrl(manifest, product())).toContain('/posts/kangxi-radicals');
	});

	it('falls back to the storefront', () => {
		expect(buyUrl(manifest, product({ buyUrl: '' }))).toBe(manifest.shop);
	});

	// `base` is stubbed to '' in tests; the point is that a site-relative href
	// goes through it and an external one does not.
	it('leaves an external free-alternative href alone', () => {
		const p = product({
			freeAlternative: { label: 'x', href: 'https://example.com/x' },
		});
		expect(freeHref(p)).toBe('https://example.com/x');
	});

	it('prefixes a site-relative free-alternative href', () => {
		const p = product({
			freeAlternative: { label: 'Radicals', href: '/radicals' },
		});
		expect(freeHref(p)).toBe('/radicals');
	});

	it('has no free link when the manifest names none', () => {
		expect(freeHref(product())).toBeNull();
	});
});

describe('images', () => {
	it('points at static/img/shop', () => {
		expect(productImage(product({ image: 'kangxi-radicals.jpg' }))).toBe(
			'/img/shop/kangxi-radicals.jpg',
		);
	});

	// No image is the normal state until the shots are taken by hand, so it must
	// be a null the card can fall back on, not a broken path.
	it('is null when the manifest names no file', () => {
		expect(productImage(product())).toBeNull();
	});

	it('gives every product a fallback glyph', () => {
		expect(tileGlyph(product())).toBe('部');
		expect(tileGlyph(product({ id: 'something-new' }))).toBe('汉');
	});
});
