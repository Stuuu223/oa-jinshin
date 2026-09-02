Vue.component('sub-menu', {
    props: ['menus', 'fold'],
    methods: {
        openTab(data) {
            window.app.openTab(data);
        }
    },
    computed: {
        // 我的客户角色提示(总经办/组长/销售)——服务端注入 window._mmHint,Vue 原生渲染,重渲染(is-active/路由切换)不清掉(老板 09-03:JS 装饰版点击后提示消失)
        mmHint: function () { return window._mmHint || ''; }
    },
    template: `
        <div>
            <template v-for="(item,i) in menus" :key="item.eid">
                <el-menu-item  :index="item.eid" v-if="!item.models" @click="openTab(item,item.eid)" :class="{'mm-item': item.name === '我的客户'}">
                    <i :class="'menu-icon '+item.icon"></i>
                    <span v-show="!fold">{{item.name}}<span v-if="item.name === '我的客户'" class="mm-hint">{{mmHint}}</span></span>
                </el-menu-item>
                <el-submenu :index="item.eid" v-else>
                    <template slot="title">
                        <i :class="'menu-icon '+item.icon"></i>
                        <span v-show="!fold">{{item.name}}</span>
                    </template>
                   <sub-menu :menus="item.models"></sub-menu>
                </el-submenu>
            </template>
        </div>
    `

});
Vue.component('multiple-menu', {
    props: ['menus', 'menuActive', 'fold'],
    computed: {
        // 老板要求(2026-08-31):菜单点击互不收缩(unique-opened=false)+ 所有层级子菜单默认全部展开(不管一级二级)
        defaultOpeneds: function () {
            var out = [];
            var walk = function (list) {
                (list || []).forEach(function (item) {
                    if (item.models && item.models.length && item.eid) {
                        out.push(item.eid);
                        walk(item.models);
                    }
                });
            };
            walk(this.menus);
            return out;
        }
    },
    template: `
     <el-menu :unique-opened="false" :default-active="menuActive" :default-openeds="defaultOpeneds" :collapse="fold" :collapse-transition="true">
        <sub-menu :menus="menus" :fold="fold"></sub-menu>
    </el-menu>
    `
});
