Vue.component('sub-menu', {
    props: ['menus', 'fold'],
    methods: {
        openTab(data) {
            window.app.openTab(data);
        }
    },
    template: `
        <div>
            <template v-for="(item,i) in menus" :key="item.eid">
                <el-menu-item  :index="item.eid" v-if="!item.models" @click="openTab(item,item.eid)">
                    <i :class="'menu-icon '+item.icon"></i>
                    <span v-show="!fold">{{item.name}}</span>
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
        // 老板要求(2026-08-30):菜单点击互不收缩(unique-opened=false)+ 默认展开「客户管理」
        defaultOpeneds: function () {
            var out = [];
            (this.menus || []).forEach(function (item) {
                if (item.name === '客户管理' && item.eid) { out.push(item.eid); }
            });
            return out;
        }
    },
    template: `
     <el-menu :unique-opened="false" :default-active="menuActive" :default-openeds="defaultOpeneds" :collapse="fold" :collapse-transition="true">
        <sub-menu :menus="menus" :fold="fold"></sub-menu>
    </el-menu>
    `
});
