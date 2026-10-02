export function createTrayIcon(nativeImage) {
  const size = 32;
  const pixels = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const inset = x < 3 || x > 28 || y < 3 || y > 28;
    const stroke = y >= 9 && y <= 23 && (Math.abs(x - (8 + (y - 9) / 3)) < 2 || Math.abs(x - (16 - (y - 9) / 3)) < 2 || Math.abs(x - (16 + (y - 9) / 3)) < 2 || Math.abs(x - (24 - (y - 9) / 3)) < 2);
    const offset = (y * size + x) * 4;
    // Windows nativeImage bitmaps use BGRA pixels.
    pixels[offset] = stroke ? 20 : 100;
    pixels[offset + 1] = stroke ? 20 : 255;
    pixels[offset + 2] = stroke ? 20 : 195;
    pixels[offset + 3] = inset ? 0 : 255;
  }
  return nativeImage.createFromBitmap(pixels, { width: size, height: size, scaleFactor: 1 });
}
