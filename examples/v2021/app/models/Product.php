<?php
class Product
{
    public static function getById($id)
    {
        return R::findOne('product', 'id = ? AND status = 1', [$id]);
    }

    public static function getByCategory($category, $page = 1)
    {
        $per = 20;
        $items = R::find('product', 'category_id = ? AND status = 1 LIMIT ?, ?',
            [$category, ($page - 1) * $per, $per]);
        $total = R::count('product', 'category_id = ? AND status = 1', [$category]);
        return ['items' => $items, 'pages' => ceil($total / $per)];
    }

    public static function getColors($id)
    {
        return R::getAll('SELECT c.title FROM modification m
            JOIN color c ON c.id = m.color_id WHERE m.product_id = ?', [$id]);
    }

    public static function getSizes($id)
    {
        return R::getAll('SELECT s.title FROM registr r
            JOIN sizes s ON s.id = r.size_id WHERE r.product_id = ? AND r.amount > 0', [$id]);
    }

    public static function getSimilar($id, $limit = 8)
    {
        return R::find('product', 'id <> ? AND status = 1 LIMIT ?', [$id, $limit]);
    }

    public static function search($query)
    {
        $words = preg_split('/\s+/', trim($query));
        $where = [];
        $params = [];
        foreach ($words as $w) {
            $where[] = 'index_search LIKE ?';
            $params[] = '%' . mb_strtolower($w) . '%';
        }
        return R::getAll('SELECT ids, title, link FROM indexproduct WHERE '
            . implode(' AND ', $where) . ' LIMIT 50', $params);
    }
}
