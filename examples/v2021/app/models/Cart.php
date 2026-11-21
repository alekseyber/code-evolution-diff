<?php
class Cart
{
    public static function add($productId, $sizeId, $qty = 1)
    {
        $key = $productId . ':' . $sizeId;
        $_SESSION['cart'][$key] = ($_SESSION['cart'][$key] ?? 0) + $qty;
        return self::count();
    }

    public static function count()
    {
        return array_sum($_SESSION['cart'] ?? []);
    }
}
