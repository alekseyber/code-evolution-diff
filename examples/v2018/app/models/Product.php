<?php
class Product
{
    public static function getById($id)
    {
        return R::findOne('product', 'id = ?', [$id]);
    }

    public static function getByCategory($category)
    {
        return R::find('product', 'category_id = ? AND status = 1', [$category]);
    }

    public static function getPrice($id)
    {
        $p = self::getById($id);
        return $p ? $p->price : 0;
    }
}
