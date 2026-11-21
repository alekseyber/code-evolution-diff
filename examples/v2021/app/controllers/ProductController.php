<?php
class ProductController
{
    public function actionView($id)
    {
        $product = Product::getById($id);
        if (!$product) {
            return $this->notFound();
        }

        $colors = Product::getColors($id);
        $sizes = Product::getSizes($id);
        $similar = Product::getSimilar($id, 8);

        return $this->render('product/view', [
            'product' => $product,
            'colors' => $colors,
            'sizes' => $sizes,
            'similar' => $similar,
        ]);
    }

    public function actionList($category, $page = 1)
    {
        $data = Product::getByCategory($category, $page);
        return $this->render('product/list', [
            'products' => $data['items'],
            'pages' => $data['pages'],
            'filters' => Filter::getForCategory($category),
        ]);
    }

    public function actionSearch($query)
    {
        $result = Product::search($query);
        return $this->render('product/search', [
            'products' => $result,
            'count' => count($result),
        ]);
    }

    public function actionCity($code)
    {
        $page = CityPage::getByCode($code);
        return $this->render('product/city', ['page' => $page]);
    }
}
