<?php
class Order
{
    public static function create($data)
    {
        R::begin();
        try {
            $order = R::dispense('order');
            $order->name = $data['name'];
            $order->phone = $data['phone'];
            $id = R::store($order);
            R::commit();
            return $id;
        } catch (Exception $e) {
            R::rollback();
            return false;
        }
    }
}
